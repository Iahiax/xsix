from __future__ import annotations

import hmac
import io
import json
import os
import time
import uuid
from datetime import datetime, timezone
from typing import Any

import spaces
import gradio as gr
from fastapi import FastAPI, Header, HTTPException, Request

from arabic_evaluation import (
    EVALUATION_CASES,
    EVALUATION_SUITE_VERSION,
    apply_semantic_reviews,
    evaluate_responses,
    model_artifact_fingerprint,
    promotion_report_is_valid,
    restore_pending_evaluation_report,
    suite_fingerprint,
)
from feedback_store import save_correction
from error_monitor import get_error_snapshot, record_error
from capital_market import CapitalMarketError, capital_market_client
from quant_engine import (
    QuantDataError,
    analyze_market,
    risk_position_size,
    technical_indicators,
    trend_signal,
    validate_candles,
)
from quant_store import quant_store
from model_runtime import (
    PROJECT_MODEL_ID,
    SAFETY_SYSTEM_PROMPT,
    evaluation_baseline_identity,
    evaluate_candidate_responses as _evaluate_candidate_responses,
    generate as _generate_model_response,
    model_status,
)
from trainer import train_candidate as _train_candidate
from pathlib import Path
from huggingface_hub import HfApi, hf_hub_download


@spaces.GPU(duration=120)
def generate(
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]] | None = None,
    max_new_tokens: int = 512,
    temperature: float = 0.2,
) -> dict[str, Any]:
    """Run model inference through the entrypoint's discoverable ZeroGPU wrapper."""
    return _generate_model_response(
        messages,
        tools=tools,
        max_new_tokens=max_new_tokens,
        temperature=temperature,
    )


def _require_ready() -> None:
    status = model_status()
    if not status["ready"]:
        if status["state"] == "promotion_blocked":
            detail = "حُجبت المحادثة: يلزم تقرير تقييم ناجح لهذا المرشح قبل تفعيله."
        else:
            detail = "لا توجد نسخة مدرّبة ومحمّلة من نموذج المشروع؛ لم يُستخدم النموذج الأساسي كبديل."
        raise HTTPException(
            status_code=503,
            detail=detail,
        )


def _authorize_api(api_token: str) -> None:
    expected = os.getenv("SPACE_API_TOKEN", "")
    if not expected:
        raise HTTPException(status_code=503, detail="لم يُضبط رمز وصول API الخاص بالـSpace.")
    supplied = api_token.strip()
    if not supplied or not hmac.compare_digest(supplied, expected):
        raise HTTPException(status_code=401, detail="رمز وصول API غير صالح.")


api = gr.Server(title="Mersad project-trained model API")


@api.middleware("http")
async def capture_http_errors(request: Request, call_next):
    try:
        response = await call_next(request)
    except Exception:
        record_error(500, request.method, request.url.path)
        raise
    if response.status_code >= 500:
        record_error(response.status_code, request.method, request.url.path)
    return response


@api.get("/health")
def health(
    api_token: str = Header(default="", alias="X-Space-Api-Token"),
) -> dict[str, Any]:
    _authorize_api(api_token)
    return {
        **model_status(),
        "mode": "project_model_only",
        "live_trading": False,
        "demo_execution_enabled": (
            os.getenv("CAPITAL_API_MODE", "").lower() == "demo"
            and os.getenv("CAPITAL_DEMO_EXECUTION_ENABLED", "").lower() == "true"
        ),
    }


@api.get("/v1/quant/markets")
def quant_markets(
    search_term: str = "",
    api_token: str = Header(default="", alias="X-Space-Api-Token"),
) -> dict[str, Any]:
    _authorize_api(api_token)
    try:
        markets = capital_market_client.search_markets(search_term)
        return {"source": "Capital.com", "markets": markets}
    except CapitalMarketError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error


@api.get("/v1/quant/candles")
def quant_candles(
    epic: str,
    resolution: str = "HOUR",
    max_bars: int = 500,
    api_token: str = Header(default="", alias="X-Space-Api-Token"),
) -> dict[str, Any]:
    _authorize_api(api_token)
    try:
        candles = capital_market_client.fetch_candles(epic, resolution, max_bars)
        candles = validate_candles(candles)
        quant_store.save_candles(epic, resolution, candles, source="Capital.com")
        return {
            "epic": epic,
            "resolution": resolution,
            "source": "Capital.com",
            "count": len(candles),
            "candles": candles,
        }
    except CapitalMarketError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    except QuantDataError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@api.post("/v1/quant/analyze")
def quant_analyze(
    payload: dict[str, Any],
    api_token: str = Header(default="", alias="X-Space-Api-Token"),
) -> dict[str, Any]:
    _authorize_api(api_token)
    epic = payload.get("epic")
    resolution = payload.get("resolution", "HOUR")
    max_bars = payload.get("max_bars", 500)
    starting_equity = payload.get("starting_equity")
    commission_bps = payload.get("commission_bps", 0.0)
    contract_multiplier = payload.get("contract_multiplier", 1.0)
    if not isinstance(epic, str) or not epic.strip():
        raise HTTPException(status_code=422, detail="رمز السوق Epic مطلوب.")
    if isinstance(starting_equity, bool) or not isinstance(starting_equity, (int, float)):
        raise HTTPException(status_code=422, detail="الرصيد الابتدائي مطلوب للاختبار.")
    if isinstance(commission_bps, bool) or not isinstance(commission_bps, (int, float)):
        raise HTTPException(status_code=422, detail="العمولة يجب أن تكون رقماً.")
    if isinstance(contract_multiplier, bool) or not isinstance(contract_multiplier, (int, float)):
        raise HTTPException(status_code=422, detail="معامل العقد يجب أن يكون رقماً.")
    try:
        candles = validate_candles(
            capital_market_client.fetch_candles(epic.strip(), str(resolution), int(max_bars))
        )
        quant_store.save_candles(epic.strip(), str(resolution), candles, source="Capital.com")
        report = analyze_market(
            candles,
            starting_equity=float(starting_equity),
            commission_bps=float(commission_bps),
            contract_multiplier=float(contract_multiplier),
        )
        run_id = str(uuid.uuid4())
        quant_store.save_run(
            run_id,
            epic.strip(),
            str(resolution),
            len(candles),
            report,
            source="Capital.com",
        )
        return {
            "run_id": run_id,
            "epic": epic.strip(),
            "resolution": str(resolution),
            "source": "Capital.com",
            "report": report,
        }
    except CapitalMarketError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    except (QuantDataError, TypeError, ValueError) as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@api.get("/v1/quant/runs")
def quant_runs(
    limit: int = 20,
    api_token: str = Header(default="", alias="X-Space-Api-Token"),
) -> dict[str, Any]:
    _authorize_api(api_token)
    try:
        return {"runs": quant_store.list_runs(limit)}
    except (TypeError, ValueError):
        raise HTTPException(status_code=422, detail="حد نتائج التحليل غير صالح.") from None


@api.get("/diagnostics/errors")
def diagnostics_errors(
    api_token: str = Header(default="", alias="X-Space-Api-Token"),
) -> dict[str, Any]:
    _authorize_api(api_token)
    return get_error_snapshot()


@api.post("/v1/chat/completions")
def chat_completions(
    payload: dict[str, Any],
    api_token: str = Header(default="", alias="X-Space-Api-Token"),
) -> dict[str, Any]:
    _authorize_api(api_token)
    _require_ready()
    messages = payload.get("messages")
    if not isinstance(messages, list) or not messages:
        raise HTTPException(status_code=400, detail="يجب إرسال قائمة رسائل.")
    if len(messages) > 40:
        raise HTTPException(status_code=400, detail="سجل المحادثة أطول من الحد المسموح.")
    if any(not isinstance(item, dict) or item.get("role") not in {"system", "user", "assistant", "tool"} for item in messages):
        raise HTTPException(status_code=400, detail="تحتوي قائمة الرسائل على دور غير صالح.")

    tools = payload.get("tools")
    if not isinstance(tools, list):
        tools = None
    try:
        result = generate(
            messages,
            tools=tools,
            max_new_tokens=payload.get("max_tokens", 512),
            temperature=payload.get("temperature", 0.2),
        )
    except RuntimeError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    except Exception as error:
        print(f"Project model generation failed: {type(error).__name__}")
        raise HTTPException(status_code=503, detail="تعذر تشغيل نسخة نموذج المشروع.") from error

    message: dict[str, Any] = {"role": "assistant", "content": result["content"] or None}
    finish_reason = "stop"
    if result["tool_calls"]:
        message["tool_calls"] = result["tool_calls"]
        finish_reason = "tool_calls"
    return {
        "id": f"chatcmpl-{uuid.uuid4().hex}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": PROJECT_MODEL_ID,
        "choices": [{"index": 0, "message": message, "finish_reason": finish_reason}],
    }


@spaces.GPU(duration=120)
def _respond(
    message: str,
    history: list[dict[str, str]] | None,
) -> tuple[str, list[dict[str, str]], list[dict[str, str]], str, str]:
    if not message.strip():
        current_history = history or []
        return "", current_history, current_history, "", ""
    status = model_status()
    if not status["ready"]:
        if status["state"] == "promotion_blocked":
            raise gr.Error("حُجبت المحادثة: يلزم تقرير تقييم ناجح للنموذج المضبوط قبل تفعيله.")
        raise gr.Error("لم تُنشأ نسخة مدرّبة بعد. ارفع أمثلة حوارية مصححة وأنشئ مرشح التدريب أولاً.")

    previous = history or []
    messages = [{"role": "system", "content": SAFETY_SYSTEM_PROMPT}]
    messages.extend(previous)
    messages.append({"role": "user", "content": message.strip()})
    result = _generate_model_response(messages, max_new_tokens=512, temperature=0.2)
    reply = result["content"] or "لم يُرجع النموذج نصاً."
    updated = previous + [
        {"role": "user", "content": message.strip()},
        {"role": "assistant", "content": reply},
    ]
    return "", updated, updated, message.strip(), reply


def _save_correction(prompt: str, correction: str, request: gr.Request) -> str:
    _require_semantic_reviewer(request)
    if not prompt.strip() or not correction.strip():
        raise gr.Error("أرسل سؤالاً أولاً ثم اكتب الإجابة المصححة.")
    try:
        path = save_correction(prompt, correction)
    except Exception as error:
        raise gr.Error(str(error)) from error
    return f"حُفظ مثال التصحيح الخاص: {path}. لن يبدأ التدريب تلقائياً."


@spaces.GPU(duration=240)
def _train(uploaded_jsonl: str | None, request: gr.Request) -> str:
    _require_semantic_reviewer(request)
    try:
        return _train_candidate(uploaded_jsonl)
    except Exception as error:
        raise gr.Error(str(error)) from error


def _review_table_rows(report: dict[str, Any]) -> list[list[str]]:
    return [
        [
            case["case_id"],
            case["semantic_review"]["guidance"],
            case["semantic_review"]["outcome"],
            case["semantic_review"]["notes"],
        ]
        for case in report["candidate"]["cases"]
    ]


def _review_prompt_rows(report: dict[str, Any]) -> list[list[str]]:
    evaluated_cases = {
        case["case_id"]: case
        for case in report.get("candidate", {}).get("cases", [])
        if isinstance(case, dict) and isinstance(case.get("case_id"), str)
    }
    rows = []
    for case_definition in EVALUATION_CASES:
        case = evaluated_cases.get(case_definition["id"], {})
        rows.append(
            [
                case_definition["id"],
                "canonical",
                case_definition["prompt"],
                case.get("response", ""),
            ]
        )
        saved_variants = {
            variant.get("variant_id"): variant
            for variant in case.get("prompt_variants", [])
            if isinstance(variant, dict)
        }
        for variant_definition in case_definition.get("prompt_variants", []):
            saved_variant = saved_variants.get(variant_definition["id"], {})
            rows.append(
                [
                    case_definition["id"],
                    variant_definition["locale"],
                    variant_definition["prompt"],
                    saved_variant.get("response", ""),
                ]
            )
    return rows


def _upload_evaluation_report(
    api_client: HfApi,
    report: dict[str, Any],
    candidate_model_id: str,
    write_token: str,
) -> None:
    serialized = json.dumps(report, ensure_ascii=False, indent=2).encode("utf-8")
    api_client.upload_file(
        path_or_fileobj=io.BytesIO(serialized),
        path_in_repo="evaluation/latest.json",
        repo_id=candidate_model_id,
        repo_type="model",
        token=write_token,
        commit_message="Store held-out Arabic evaluation report",
    )
    archive_name = (
        f"evaluation/reports/{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}-"
        f"{uuid.uuid4().hex[:8]}.json"
    )
    api_client.upload_file(
        path_or_fileobj=io.BytesIO(serialized),
        path_in_repo=archive_name,
        repo_id=candidate_model_id,
        repo_type="model",
        token=write_token,
        commit_message="Archive held-out Arabic evaluation report",
    )


@spaces.GPU(duration=240)
def _evaluate_candidate(
    candidate_model_id: str,
    request: gr.Request,
) -> tuple[dict[str, Any], str, list[list[str]], list[list[str]], dict[str, Any]]:
    _require_semantic_reviewer(request)
    candidate_model_id = candidate_model_id.strip()
    candidate_prefix = os.getenv("CANDIDATE_MODEL_REPO_PREFIX", "").strip().rstrip("/")
    write_token = os.getenv("HF_WRITE_TOKEN") or os.getenv("HF_TOKEN")
    if not candidate_prefix or not candidate_model_id.startswith(f"{candidate_prefix}-candidate-"):
        raise gr.Error("أدخل معرف مرشح أنشأه تدريب مرصاد ضمن بادئة المستودع المضبوطة.")
    if candidate_model_id == PROJECT_MODEL_ID:
        raise gr.Error("يجب أن يكون المرشح مختلفاً عن النموذج الحالي.")
    if not write_token:
        raise gr.Error("يلزم HF_WRITE_TOKEN لحفظ تقرير التقييم في مستودع المرشح الخاص.")

    try:
        api_client = HfApi(token=write_token)
        candidate_info = api_client.model_info(candidate_model_id, files_metadata=True)
        if getattr(candidate_info, "private", False) is not True:
            raise RuntimeError("يجب أن يكون مستودع المرشح خاصاً لحماية أوزانه وتقرير التقييم.")
        candidate_fingerprint = model_artifact_fingerprint(candidate_info)
        if not candidate_info.sha or not candidate_fingerprint:
            raise RuntimeError("تعذر تثبيت إصدار ملفات المرشح.")
        baseline = evaluation_baseline_identity()
        responses = _evaluate_candidate_responses(candidate_model_id, candidate_info.sha)
        latest_candidate_info = api_client.model_info(candidate_model_id, files_metadata=True)
        if model_artifact_fingerprint(latest_candidate_info) != candidate_fingerprint:
            raise RuntimeError("تغيرت ملفات المرشح أثناء التقييم؛ أعد تشغيل التقييم.")
        candidate_evaluation = evaluate_responses(responses["candidate"])
        baseline_evaluation = evaluate_responses(responses["baseline"])
        report = {
            "suite_version": EVALUATION_SUITE_VERSION,
            "suite_fingerprint": suite_fingerprint(),
            "candidate_model_id": candidate_model_id,
            "candidate_revision": candidate_info.sha,
            "candidate_artifact_fingerprint": candidate_fingerprint,
            "baseline_model_id": baseline["model_id"],
            "baseline_revision": baseline["revision"],
            "evaluated_at": datetime.now(timezone.utc).isoformat(),
            "candidate": candidate_evaluation,
            "baseline": baseline_evaluation,
            "semantic_review": {
                "status": "pending",
                "reviewer": "",
                "reviewer_verified": False,
                "reviewer_provider": "",
                "reviewed_at": "",
            },
            "promotion_eligible": False,
        }
        report["promotion_eligible"] = promotion_report_is_valid(
            report,
            candidate_model_id,
            candidate_fingerprint,
        )
        _upload_evaluation_report(api_client, report, candidate_model_id, write_token)
        status_message = (
            "اكتمل التقييم الآلي. افحص الأسئلة الأساسية وكل صيغها اللهجية وإجاباتها، "
            "ثم سجّل قراراً لكل حالة أساسية وفق الإرشادات المعتمدة. تُسجّل هوية حساب Hugging Face الموثق تلقائياً؛ "
            "الترقية محجوبة حتى قبول الحالات الحرجة."
        )
        return (
            report,
            status_message,
            _review_prompt_rows(report),
            _review_table_rows(report),
            report,
        )
    except gr.Error:
        raise
    except Exception as error:
        raise gr.Error(f"تعذر إكمال التقييم أو حفظ تقريره: {type(error).__name__}.") from error

def _load_pending_evaluation_report(
    candidate_model_id: str,
    request: gr.Request,
) -> tuple[dict[str, Any], str, list[list[str]], list[list[str]], dict[str, Any]]:
    _require_semantic_reviewer(request)
    candidate_model_id = candidate_model_id.strip()
    candidate_prefix = os.getenv("CANDIDATE_MODEL_REPO_PREFIX", "").strip().rstrip("/")
    write_token = os.getenv("HF_WRITE_TOKEN") or os.getenv("HF_TOKEN")
    if not candidate_prefix or not candidate_model_id.startswith(f"{candidate_prefix}-candidate-"):
        raise gr.Error("أدخل معرف مرشح أنشأه تدريب مرصاد ضمن بادئة المستودع المضبوطة.")
    if not write_token:
        raise gr.Error("يلزم HF_WRITE_TOKEN لقراءة تقرير التقييم من مستودع المرشح الخاص.")

    try:
        api_client = HfApi(token=write_token)
        candidate_info = api_client.model_info(candidate_model_id, files_metadata=True)
        if getattr(candidate_info, "private", False) is not True:
            raise RuntimeError("يجب أن يكون مستودع المرشح خاصاً لحماية تقريره.")
        current_fingerprint = model_artifact_fingerprint(candidate_info)
        if not candidate_info.sha or not current_fingerprint:
            raise RuntimeError("تعذر تثبيت إصدار ملفات المرشح.")
        report_path = hf_hub_download(
            repo_id=candidate_model_id,
            filename="evaluation/latest.json",
            repo_type="model",
            revision=candidate_info.sha,
            token=write_token,
        )
        saved_report = json.loads(Path(report_path).read_text(encoding="utf-8"))
        report = restore_pending_evaluation_report(
            saved_report,
            candidate_model_id,
            current_fingerprint,
        )
        if report is None:
            raise gr.Error(
                "لا يوجد تقرير تقييم معلّق صالح لهذا المرشح أو أن ملفاته/مجموعة التقييم تغيّرت."
            )
        status_message = (
            "استُعيد تقرير التقييم المحفوظ دون إعادة تشغيل النموذج. "
            "كل قرارات المراجعة ما زالت معلّقة؛ احفظ المراجعة بعد فحص جميع الإجابات."
        )
        return (
            report,
            status_message,
            _review_prompt_rows(report),
            _review_table_rows(report),
            report,
        )
    except gr.Error:
        raise
    except Exception as error:
        raise gr.Error(
            f"تعذر تحميل تقرير التقييم المحفوظ: {type(error).__name__}."
        ) from error

def _require_semantic_reviewer(request: gr.Request) -> dict[str, Any]:
    username = getattr(request, "username", None)
    if not isinstance(username, str) or not username.strip():
        raise gr.Error("سجّل الدخول إلى Hugging Face بحساب مخوّل لإدارة مرشحي النموذج.")
    allowed_usernames = {
        name.strip().casefold()
        for name in os.getenv("SEMANTIC_REVIEWER_USERNAMES", "").split(",")
        if name.strip()
    }
    if not allowed_usernames:
        raise gr.Error("لم تُضبط قائمة حسابات المشرفين المصرّح لهم في إعدادات Space.")
    if username.strip().casefold() not in allowed_usernames:
        raise gr.Error("حساب Hugging Face هذا غير مخوّل لإدارة مرشحي النموذج.")
    return {
        "username": username.strip(),
        "provider": "huggingface_oauth",
        "verified": True,
    }


def _require_demo_operator(request: gr.Request) -> str:
    username = getattr(request, "username", None)
    if not isinstance(username, str) or not username.strip():
        raise gr.Error("سجّل الدخول إلى Hugging Face قبل طلب أمر تجريبي.")
    allowed = {
        name.strip().casefold()
        for name in os.getenv("CAPITAL_DEMO_OPERATOR_USERNAMES", "").split(",")
        if name.strip()
    }
    if not allowed or username.strip().casefold() not in allowed:
        raise gr.Error("حساب Hugging Face هذا غير مخوّل لإرسال أوامر تجريبية.")
    if os.getenv("CAPITAL_API_MODE", "").strip().lower() != "demo":
        raise gr.Error("حُظر التنفيذ: واجهة Capital.com ليست مضبوطة على البيئة التجريبية.")
    if os.getenv("CAPITAL_DEMO_EXECUTION_ENABLED", "").strip().lower() != "true":
        raise gr.Error("تنفيذ الأوامر التجريبية مقفل حتى تفعّله صراحةً في أسرار Space.")
    return username.strip()


def _fetch_quant_data(
    epic: str,
    resolution: str,
    max_bars: int,
) -> tuple[dict[str, Any], str, list[list[Any]]]:
    try:
        candles = validate_candles(
            capital_market_client.fetch_candles(epic, resolution, int(max_bars))
        )
        quant_store.save_candles(epic, resolution, candles, source="Capital.com")
        rows = technical_indicators(candles)
        table = [
            [
                row["timestamp"],
                row["close"],
                row["rsi"],
                row["macd"],
                row["atr"],
                row["ema20"],
                row["ema50"],
                row["trend"],
                row["zigzag"],
            ]
            for row in rows[-100:]
        ]
        return (
            {"epic": epic, "resolution": resolution, "source": "Capital.com", "candles": candles},
            f"تم جلب {len(candles)} شمعة حقيقية من Capital.com وحفظها في SQLite المحلي.",
            table,
        )
    except (CapitalMarketError, QuantDataError, TypeError, ValueError) as error:
        raise gr.Error(str(error)) from error


def _run_quant_analysis(
    market_state: dict[str, Any] | None,
    starting_equity: float,
    commission_bps: float,
    contract_multiplier: float,
) -> tuple[dict[str, Any] | None, dict[str, Any], str]:
    if not isinstance(market_state, dict):
        raise gr.Error("اجلب بيانات السوق الحقيقية أولاً.")
    epic = market_state.get("epic")
    resolution = market_state.get("resolution")
    if not isinstance(epic, str) or not isinstance(resolution, str):
        raise gr.Error("بيانات السوق المحددة غير صالحة؛ أعد جلب الأسعار.")
    try:
        # Re-fetch on analysis so browser-provided state cannot substitute synthetic candles.
        candles = validate_candles(capital_market_client.fetch_candles(epic, resolution, 500))
        quant_store.save_candles(epic, resolution, candles, source="Capital.com")
        report = analyze_market(
            candles,
            starting_equity=float(starting_equity),
            commission_bps=float(commission_bps),
            contract_multiplier=float(contract_multiplier),
        )
        run_id = str(uuid.uuid4())
        quant_store.save_run(run_id, epic, resolution, len(candles), report, source="Capital.com")
        updated_state = {
            "epic": epic,
            "resolution": resolution,
            "source": "Capital.com",
            "candles": candles,
            "report": report,
        }
        return updated_state, {"run_id": run_id, **report}, f"اكتمل التحليل خارج العينة؛ رقم التقرير: {run_id}."
    except (CapitalMarketError, QuantDataError, TypeError, ValueError) as error:
        raise gr.Error(str(error)) from error


def _submit_demo_order(
    market_state: dict[str, Any] | None,
    direction: str,
    size: float,
    stop_level: float,
    profit_level: float,
    account_equity: float,
    contract_multiplier: float,
    risk_fraction: float,
    confirmed: bool,
    request: gr.Request,
) -> dict[str, Any]:
    _require_demo_operator(request)
    if confirmed is not True:
        raise gr.Error("يجب تأكيد أن الأمر سيُرسل إلى حساب Capital.com التجريبي فقط.")
    if not isinstance(market_state, dict) or not isinstance(market_state.get("epic"), str):
        raise gr.Error("شغّل التحليل على بيانات حقيقية أولاً.")
    epic = market_state["epic"]
    resolution = market_state.get("resolution", "HOUR")
    try:
        # Always re-check the provider signal and live demo quote immediately before the order.
        candles = validate_candles(capital_market_client.fetch_candles(epic, resolution, 500))
        report = analyze_market(
            candles,
            starting_equity=float(account_equity),
            contract_multiplier=float(contract_multiplier),
        )
        probabilities = report.get("latest_probabilities")
        signal = (
            trend_signal(report["latest_indicators"], probabilities)
            if isinstance(probabilities, list) and len(probabilities) == 3
            else "hold"
        )
        expected_direction = {"BUY": "buy", "SELL": "sell"}.get(direction)
        if signal == "hold" or signal != expected_direction:
            raise gr.Error("لم يؤكد فلتر الاتجاه والشبكة العصبية هذا الاتجاه الآن؛ لم يُرسل أي أمر.")
        quote = capital_market_client.market_quote(epic)
        entry = quote["ask"] if direction == "BUY" else quote["bid"]
        stop = float(stop_level)
        target = float(profit_level)
        if direction == "BUY" and not stop < entry < target:
            raise gr.Error("للشراء يجب أن يكون وقف الخسارة أدنى من السعر الحالي والهدف أعلى منه.")
        if direction == "SELL" and not target < entry < stop:
            raise gr.Error("للبيع يجب أن يكون الهدف أدنى من السعر الحالي ووقف الخسارة أعلى منه.")
        risk_distance = abs(entry - stop)
        reward_distance = abs(target - entry)
        if reward_distance / risk_distance < 1.5:
            raise gr.Error("نسبة العائد إلى المخاطرة يجب ألا تقل عن 1.5.")
        size_value = float(size)
        sizing = risk_position_size(
            equity=float(account_equity),
            entry_price=entry,
            stop_price=stop,
            risk_fraction=float(risk_fraction),
            contract_multiplier=float(contract_multiplier),
        )
        if size_value <= 0 or size_value > sizing["units"]:
            raise gr.Error(
                f"الحجم يتجاوز سقف إدارة المخاطر. الحد المحسوب: {sizing['units']:.6g} وحدة."
            )
        order = capital_market_client.submit_demo_order(
            epic=epic,
            direction=direction,
            size=size_value,
            stop_level=stop,
            profit_level=target,
        )
        return {
            "mode": "demo",
            "signal": signal,
            "market_quote": quote,
            "risk_budget": sizing["risk_budget"],
            "estimated_units_cap": sizing["units"],
            "order_confirmation": order,
            "live_trading": False,
        }
    except gr.Error:
        raise
    except (CapitalMarketError, QuantDataError, TypeError, ValueError) as error:
        raise gr.Error(str(error)) from error


def _save_semantic_review(
    candidate_model_id: str,
    review_rows: list[list[str]],
    report: dict[str, Any] | None,
    request: gr.Request,
) -> tuple[dict[str, Any], str, list[list[str]], list[list[str]], dict[str, Any]]:
    reviewer_identity = _require_semantic_reviewer(request)
    candidate_model_id = candidate_model_id.strip()
    candidate_prefix = os.getenv("CANDIDATE_MODEL_REPO_PREFIX", "").strip().rstrip("/")
    write_token = os.getenv("HF_WRITE_TOKEN") or os.getenv("HF_TOKEN")
    if not candidate_prefix or not candidate_model_id.startswith(f"{candidate_prefix}-candidate-"):
        raise gr.Error("أدخل معرف مرشح أنشأه تدريب مرصاد ضمن بادئة المستودع المضبوطة.")
    if not write_token:
        raise gr.Error("يلزم HF_WRITE_TOKEN لحفظ تقرير التقييم في مستودع المرشح الخاص.")
    if not isinstance(report, dict) or report.get("candidate_model_id") != candidate_model_id:
        raise gr.Error("شغّل التقييم لهذا المرشح قبل إرسال المراجعة الدلالية.")
    if not isinstance(review_rows, list) or len(review_rows) != len(EVALUATION_CASES):
        raise gr.Error("يجب مراجعة كل حالة تقييم دون حذف صفوف.")

    canonical_results = {
        item["case_id"]: item for item in report.get("candidate", {}).get("cases", [])
    }
    reviews: dict[str, dict[str, str]] = {}
    for row in review_rows:
        if not isinstance(row, (list, tuple)) or len(row) != 4:
            raise gr.Error("تعذر قراءة جدول المراجعة؛ أعد تشغيل التقييم.")
        case_id, guidance, outcome, notes = row
        if not all(isinstance(value, str) for value in row):
            raise gr.Error("يجب أن تكون قيم جدول المراجعة نصوصاً.")
        original = canonical_results.get(case_id)
        if (
            original is None
            or guidance != original["semantic_review"]["guidance"]
            or case_id in reviews
        ):
            raise gr.Error("لا تعدّل معرف الحالة أو إرشادات المراجعة في جدول المراجعة.")
        reviews[case_id] = {"outcome": outcome.strip().lower(), "notes": notes}

    try:
        updated_report = dict(report)
        updated_report["candidate"] = apply_semantic_reviews(
            report["candidate"],
            reviews,
            reviewer_identity,
        )
        updated_report["semantic_review"] = {
            "status": "complete",
            "reviewer": reviewer_identity["username"],
            "reviewer_verified": True,
            "reviewer_provider": reviewer_identity["provider"],
            "reviewed_at": datetime.now(timezone.utc).isoformat(),
        }
        api_client = HfApi(token=write_token)
        current_info = api_client.model_info(candidate_model_id, files_metadata=True)
        if getattr(current_info, "private", False) is not True:
            raise gr.Error("يجب أن يبقى مستودع المرشح خاصاً؛ لم تُحفظ المراجعة.")
        current_fingerprint = model_artifact_fingerprint(current_info)
        if current_fingerprint != updated_report["candidate_artifact_fingerprint"]:
            raise RuntimeError("تغيرت ملفات المرشح بعد التقييم؛ أعد تشغيل التقييم.")
        updated_report["promotion_eligible"] = promotion_report_is_valid(
            updated_report,
            candidate_model_id,
            current_fingerprint,
        )
        _upload_evaluation_report(api_client, updated_report, candidate_model_id, write_token)
    except gr.Error:
        raise
    except Exception as error:
        raise gr.Error(f"تعذر حفظ المراجعة الدلالية: {type(error).__name__}.") from error

    if updated_report["promotion_eligible"]:
        status_message = (
            "اجتاز المرشح التقييم الآلي والمراجعة الدلالية. الترقية ليست تلقائية؛ "
            "غيّر PROJECT_MODEL_ID يدوياً إلى معرف هذا المرشح ثم أعد تشغيل Space."
        )
    elif not updated_report["candidate"]["summary"]["semantic_review_complete"]:
        status_message = "المراجعة غير مكتملة؛ لن يُقبل المرشح كنموذج نشط."
    elif not updated_report["candidate"]["summary"]["semantic_review_passed"]:
        status_message = "رُفضت حالة حرجة واحدة أو أكثر؛ الترقية محجوبة."
    else:
        status_message = "لم يجتز المرشح الفحوص الآلية؛ الترقية محجوبة."
    return (
        updated_report,
        status_message,
        _review_prompt_rows(updated_report),
        _review_table_rows(updated_report),
        updated_report,
    )


SPACE_CSS = """
@import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Sans+Arabic:wght@400;500;600;700&family=IBM+Plex+Mono:wght@400;500;600&display=swap');
:root {
  --mersad-ink: #183b3b;
  --mersad-deep: #102e30;
  --mersad-paper: #f4f3ed;
  --mersad-card: #fbfaf6;
  --mersad-line: #d8ded5;
  --mersad-muted: #667873;
  --mersad-coral: #a7513a;
  --mersad-sage: #dce8dc;
  --mersad-gold: #d5a957;
}
body, .gradio-container {
  background: var(--mersad-paper) !important;
  color: var(--mersad-ink) !important;
  font-family: 'IBM Plex Sans Arabic', sans-serif !important;
}
.gradio-container { max-width: 1160px !important; margin: 0 auto !important; }
.gradio-container * { font-family: 'IBM Plex Sans Arabic', sans-serif; }
.gradio-container code, .gradio-container pre, .gradio-container .dataframe-container {
  font-family: 'IBM Plex Mono', monospace !important;
}
.mersad-shell { direction: rtl; }
.mersad-hero {
  direction: rtl; position: relative; overflow: hidden; margin: 14px 0 18px;
  padding: clamp(20px, 4vw, 38px); border-radius: 20px;
  color: #f3f3e9; background: var(--mersad-deep);
  border: 1px solid #274a49;
}
.mersad-hero:after {
  content: ''; position: absolute; inset: 0 auto 0 0; width: 34%;
  background: repeating-linear-gradient(135deg, transparent 0 13px, rgba(213,169,87,.11) 13px 14px);
  pointer-events: none;
}
.mersad-kicker { color: #d7bd80 !important; font-size: 12px; font-weight: 600; letter-spacing: .11em; }
.mersad-hero h1 { margin: 8px 0 7px; color: #f3f3e9 !important; font-size: clamp(28px, 5vw, 43px); line-height: 1.2; font-weight: 700; }
.mersad-hero p { max-width: 720px; margin: 0; color: #cbd7ce !important; font-size: 15px; line-height: 1.9; }
.mersad-readiness {
  display: flex; align-items: center; gap: 12px; margin-top: 22px; padding: 12px 14px;
  width: fit-content; max-width: 100%; border: 1px solid rgba(228,235,222,.2);
  border-radius: 12px; background: rgba(255,255,255,.055);
}
.mersad-dot { width: 9px; height: 9px; flex: 0 0 9px; border-radius: 50%; background: #e0a178; }
.mersad-dot.ready { background: #95c9a1; }
.mersad-readiness strong { display: block; color: #fff8e9 !important; font-size: 14px; }
.mersad-readiness span { display: block; color: #c4d0c9 !important; font-size: 12px; line-height: 1.65; }
.mersad-note {
  direction: rtl; border: 1px solid var(--mersad-line); border-right: 4px solid var(--mersad-gold);
  border-radius: 12px; background: var(--mersad-card); padding: 14px 16px;
  color: var(--mersad-ink); line-height: 1.85; margin: 8px 0 16px;
}
.mersad-note.unavailable { border-right-color: var(--mersad-coral); background: #f7eee8; }
.mersad-section-title { color: var(--mersad-deep); font-size: 20px; font-weight: 700; margin: 3px 0 5px; }
.mersad-copy { color: var(--mersad-muted); line-height: 1.85; font-size: 14px; }
.tabs { direction: rtl; border-bottom: 1px solid var(--mersad-line) !important; gap: 5px !important; }
.tabs button { color: var(--mersad-muted) !important; border-radius: 10px 10px 0 0 !important; }
.tabs button.selected { color: var(--mersad-deep) !important; border-bottom: 2px solid var(--mersad-coral) !important; }
.tabitem { direction: rtl; padding-top: 17px !important; }
.gradio-container .block, .gradio-container .form { border-color: var(--mersad-line) !important; }
.gradio-container input, .gradio-container textarea, .gradio-container select {
  direction: rtl; border-radius: 10px !important; background: #fffefa !important;
}
.gradio-container button { border-radius: 10px !important; font-weight: 600 !important; }
.gradio-container button.primary { background: var(--mersad-ink) !important; }
.gradio-container button.stop { background: #8d4938 !important; }
.gradio-container .chatbot { min-height: 180px !important; }
.gradio-container .label-wrap { direction: rtl; }
.gradio-container .dataframe-container { overflow-x: auto !important; }
@media (max-width: 640px) {
  .gradio-container { padding: 0 10px !important; }
  .mersad-hero { margin-top: 8px; border-radius: 15px; padding: 21px 18px; }
  .mersad-hero p { font-size: 14px; }
  .mersad-readiness { width: auto; align-items: flex-start; }
  .tabitem { padding-top: 12px !important; }
  .gradio-container .chatbot { min-height: 150px !important; }
  .gradio-container .dataframe-container { max-width: calc(100vw - 34px); }
}
"""

_initial_status = model_status()
_chat_ready = bool(_initial_status.get("ready"))
if _chat_ready:
    _readiness_title = "نسخة المشروع جاهزة للمحادثة"
    _readiness_detail = "الأوزان النشطة اجتازت التقييم المطلوب. لا يُستدعى نموذج خارجي."
else:
    _readiness_title = "المحادثة غير متاحة حالياً"
    if _initial_status.get("state") == "promotion_blocked":
        _readiness_detail = "مرشح المشروع لم يجتز بوابة التقييم والترقية؛ لن تُحمّل أوزانه ولن يُستخدم نموذج بديل."
    elif _initial_status.get("state") == "checkpoint_load_failed":
        _readiness_detail = "تعذّر تحميل نسخة المشروع المدرّبة. المحادثة متوقفة ولا يوجد نموذج أساسي احتياطي."
    else:
        _readiness_detail = "لم تُفعّل نسخة مشروع مدرّبة ومقيّمة بعد. المحادثة متوقفة ولا يوجد نموذج أساسي احتياطي."
_readiness_class = "ready" if _chat_ready else ""
_readiness_card = (
    f'<div class="mersad-readiness" role="status" aria-live="polite">'
    f'<i class="mersad-dot {_readiness_class}" aria-hidden="true"></i>'
    f'<div><strong>{_readiness_title}</strong><span>{_readiness_detail}</span></div></div>'
)

with gr.Blocks(title="مرصاد | مساعد أبحاث التداول", css=SPACE_CSS) as demo:
    with gr.Column(elem_classes=["mersad-shell"]):
        gr.HTML(
            '<header class="mersad-hero" dir="rtl">'
            '<div class="mersad-kicker">مرصاد · مساعد أبحاث التداول</div>'
            '<h1>قراءة أدق. قرار أهدأ.</h1>'
            '<p>مساعد عربي مبني على نسخة المشروع المدرّبة، مع مختبر كمي ومسار مراجعة واضح. '
            'هذه مساحة بحثية للقراءة والتحليل؛ البيانات ومصدرها يظلان ظاهرين، والتنفيذ الحقيقي مقفل.</p>'
            f'{_readiness_card}</header>'
        )
        with gr.Tabs():
            with gr.Tab("المحادثة والتصحيحات"):
                if not _chat_ready:
                    gr.HTML(
                        '<section class="mersad-note unavailable" role="status">'
                        '<div class="mersad-section-title">المساعد لا يجيب الآن</div>'
                        '<div>لا توجد نسخة مشروع مفعّلة وجاهزة للاستخدام. أبقينا مساحة المحادثة مغلقة '
                        'بدلاً من عرض ردود تجريبية أو الرجوع إلى نموذج عام.</div></section>'
                    )
                chatbot = gr.Chatbot(
                    height=300 if _chat_ready else 165,
                    label="محادثة نسخة المشروع",
                    visible=_chat_ready,
                )
                history_state = gr.State([])
                last_prompt = gr.State("")
                last_reply = gr.State("")
                message = gr.Textbox(
                    label="رسالتك",
                    placeholder="اكتب سؤالك بالعربية…",
                    max_lines=4,
                    interactive=_chat_ready,
                )
                send = gr.Button("إرسال إلى نسخة المشروع", variant="primary", interactive=_chat_ready)
                correction = gr.Textbox(
                    label="تصحيح اختياري",
                    placeholder="اكتب الإجابة المصححة التي توافق على حفظها لتدريب لاحق.",
                    lines=3,
                    visible=_chat_ready,
                )
                save_button = gr.Button("حفظ التصحيح للتدريب اللاحق", interactive=_chat_ready, visible=_chat_ready)
                feedback_status = gr.Markdown(visible=_chat_ready)
                send.click(
                    _respond,
                    inputs=[message, history_state],
                    outputs=[message, chatbot, history_state, last_prompt, last_reply],
                )
                message.submit(
                    _respond,
                    inputs=[message, history_state],
                    outputs=[message, chatbot, history_state, last_prompt, last_reply],
                )
                save_button.click(
                    _save_correction,
                    inputs=[last_prompt, correction],
                    outputs=feedback_status,
                )
                gr.Markdown(
                    "حفظ التصحيح متاح لحساب Hugging Face المخوّل فقط. لا تحفظ كلمات مرور أو مفاتيح أو بيانات حسابات. "
                    "لا يُحفظ للتدريب إلا التصحيح الذي ترسله صراحةً. لا يُستخدم نموذج سحابي أو أساسي بديلاً عن نسخة المشروع."
                )
            with gr.Tab("المختبر الكمي"):
                gr.Markdown(
                    "بيانات تاريخية حقيقية من واجهة Capital.com التجريبية فقط عند نجاح الجلب؛ "
                    "لا تُعرض أسعار تركيبية. يشمل التحليل مؤشرات ومرشح MLP ووكيل Q-learning واختباراً "
                    "خارج العينة. ZigZag للعرض الاستعادي ولا يدخل في الإشارات. لا يوجد تداول آلي، "
                    "والتداول الحقيقي مقفل دائماً."
                )
                with gr.Row():
                    quant_epic = gr.Textbox(label="رمز السوق Epic", placeholder="أدخل رمزاً من Capital.com")
                    quant_resolution = gr.Dropdown(
                        choices=["MINUTE_5", "MINUTE_15", "MINUTE_30", "HOUR", "HOUR_4", "DAY"],
                        value="HOUR",
                        label="الإطار الزمني",
                    )
                    quant_count = gr.Slider(minimum=100, maximum=1000, step=100, value=500, label="عدد الشموع")
                fetch_quant_button = gr.Button("جلب بيانات تاريخية حقيقية", variant="primary")
                quant_market_state = gr.State(None)
                quant_data_status = gr.Markdown()
                quant_candles_table = gr.Dataframe(
                    headers=["الوقت UTC", "الإغلاق", "RSI", "MACD", "ATR", "EMA 20", "EMA 50", "SuperTrend", "ZigZag"],
                    datatype=["str", "number", "number", "number", "number", "number", "number", "number", "str"],
                    interactive=False,
                    label="آخر 100 شمعة ومؤشر",
                )
                fetch_quant_button.click(
                    _fetch_quant_data,
                    inputs=[quant_epic, quant_resolution, quant_count],
                    outputs=[quant_market_state, quant_data_status, quant_candles_table],
                )
                with gr.Row():
                    quant_equity = gr.Number(value=10_000, minimum=1, label="رصيد الاختبار (بوحدته الأصلية)")
                    quant_commission = gr.Number(value=0, minimum=0, maximum=100, label="العمولة المفترضة (نقطة أساس)")
                    quant_multiplier = gr.Number(value=1, minimum=0.000001, label="معامل العقد (تحقق منه في Capital.com)")
                analyze_quant_button = gr.Button("تدريب المرشحين وتشغيل الاختبار", variant="primary")
                quant_analysis_state = gr.State(None)
                quant_analysis_status = gr.Markdown()
                quant_report = gr.JSON(label="المؤشرات، تحقق النماذج، المخاطر، والاختبار خارج العينة")
                analyze_quant_button.click(
                    _run_quant_analysis,
                    inputs=[quant_market_state, quant_equity, quant_commission, quant_multiplier],
                    outputs=[quant_analysis_state, quant_report, quant_analysis_status],
                )
                with gr.Accordion("إرسال يدوي إلى حساب Capital.com التجريبي فقط", open=False):
                    gr.Markdown(
                        "الإرسال مقفل افتراضياً. يتطلب دخول Hugging Face وحساباً في "
                        "`CAPITAL_DEMO_OPERATOR_USERNAMES`، وبيانات Capital.com التجريبية، "
                        "وتفعيل `CAPITAL_DEMO_EXECUTION_ENABLED`. تحقّق يدوياً من معامل العقد؛ "
                        "لا يُنشأ أمر تلقائي أو حي."
                    )
                    with gr.Row():
                        demo_direction = gr.Dropdown(choices=["BUY", "SELL"], value="BUY", label="اتجاه الأمر")
                        demo_size = gr.Number(value=None, minimum=0, label="حجم الأمر")
                        demo_multiplier = gr.Number(value=None, minimum=0, label="معامل العقد من تفاصيل السوق")
                    with gr.Row():
                        demo_equity = gr.Number(value=None, minimum=1, label="رصيد حساب Demo")
                        demo_risk_fraction = gr.Dropdown(
                            choices=[0.001, 0.0025, 0.005],
                            value=0.0025,
                            label="حد المخاطرة لكل أمر",
                        )
                        demo_stop = gr.Number(value=None, minimum=0, label="وقف الخسارة")
                        demo_target = gr.Number(value=None, minimum=0, label="جني الأرباح")
                    demo_confirm = gr.Checkbox(
                        label="أؤكد إرسال أمر يدوي إلى حساب Capital.com التجريبي فقط",
                        value=False,
                    )
                    demo_order_button = gr.Button("تحقق من الإشارة والمخاطر ثم أرسل", variant="stop")
                    demo_order_result = gr.JSON(label="نتيجة تأكيد حساب Demo")
                    demo_order_button.click(
                        _submit_demo_order,
                        inputs=[
                            quant_analysis_state,
                            demo_direction,
                            demo_size,
                            demo_stop,
                            demo_target,
                            demo_equity,
                            demo_multiplier,
                            demo_risk_fraction,
                            demo_confirm,
                        ],
                        outputs=demo_order_result,
                    )
                gr.Markdown(
                    "قد تدخل مساحة Hugging Face المجانية في الخمول؛ لا يمكن ضمان تشغيل دائم أو تنفيذ على مدار الساعة. "
                    "تُحفظ الشموع والتقارير محلياً في SQLite، لكن ملفات المساحة المجانية ليست نسخة احتياطية دائمة."
                )
            with gr.Tab("التدريب"):
                gr.Markdown(
                    "إنشاء مرشح LoRA قصير ورفعه إلى مستودع خاص. ارفع أمثلة عربية مصححة بموافقتك. "
                    "التدريب يدوي ومحدود بحصة ZeroGPU، ولا يجيب النموذج "
                    "الأساسي عن المحادثة. أول مرشح يُقارن بالأساس المفتوح أثناء التقييم فقط؛ لا ترقية تلقائية."
                )
                training_file = gr.File(
                    label="ملف أمثلة JSONL اختياري",
                    file_types=[".jsonl"],
                    type="filepath",
                )
                train_button = gr.Button("إنشاء مرشح تدريب قصير", variant="primary")
                training_status = gr.Markdown()
                train_button.click(_train, inputs=training_file, outputs=training_status)
            with gr.Tab("التقييم والمراجعة"):
                gr.Markdown(
                    "شغّل مجموعة التقييم العربية الثابتة؛ يُقارن المرشح بالنموذج النشط، أو بالأساس المفتوح "
                    "للمراجعة الأولية فقط إن لم توجد نسخة مرصاد نشطة. ثم راجع كل إجابة دلالياً وسجّل القبول أو الرفض. "
                    "تُسجّل هوية حساب Hugging Face الموثق؛ أي حالة حرجة مرفوضة أو غير مراجعة تمنع الترقية. "
                    "يُحفظ التقرير والمراجعة في مستودع المرشح الخاص. اجتياز التقييم لا يفعّل النموذج؛ "
                    "تغيير `PROJECT_MODEL_ID` خطوة يدوية."
                )
                candidate_id = gr.Textbox(label="معرف مستودع المرشح", placeholder="owner/model-candidate-…")
                with gr.Row():
                    evaluate_button = gr.Button("تقييم المرشح وحفظ التقرير", variant="primary")
                    restore_button = gr.Button("تحميل التقييم المعلّق المحفوظ")
                evaluation_report = gr.JSON(label="تقرير التقييم")
                evaluation_status = gr.Markdown()
                gr.Markdown(
                    "يلزم تسجيل الدخول إلى Hugging Face بحساب موجود في قائمة "
                    "`SEMANTIC_REVIEWER_USERNAMES`."
                )
                prompt_review_table = gr.Dataframe(
                    headers=["معرف الحالة", "صيغة السؤال", "السؤال", "إجابة المرشح"],
                    datatype=["str", "str", "str", "str"],
                    type="array",
                    interactive=False,
                    label="كل الأسئلة وإجابات المرشح — للعرض فقط",
                )
                semantic_reviews = gr.Dataframe(
                    headers=["معرف الحالة", "إرشادات المراجعة", "القرار (accepted/rejected)", "ملاحظات المراجع"],
                    datatype=["str", "str", "str", "str"],
                    type="array",
                    interactive=True,
                    label="قرارات المراجعة لكل حالة أساسية",
                )
                evaluation_state = gr.State(None)
                save_review_button = gr.Button("حفظ المراجعة الدلالية")
                evaluate_button.click(
                    _evaluate_candidate,
                    inputs=candidate_id,
                    outputs=[evaluation_report, evaluation_status, prompt_review_table, semantic_reviews, evaluation_state],
                )
                restore_button.click(
                    _load_pending_evaluation_report,
                    inputs=candidate_id,
                    outputs=[evaluation_report, evaluation_status, prompt_review_table, semantic_reviews, evaluation_state],
                )
                save_review_button.click(
                    _save_semantic_review,
                    inputs=[candidate_id, semantic_reviews, evaluation_state],
                    outputs=[evaluation_report, evaluation_status, prompt_review_table, semantic_reviews, evaluation_state],
                )
            with gr.Tab("حالة النموذج والبيانات"):
                gr.HTML(
                    '<div class="mersad-note"><div class="mersad-section-title">بوابة التفعيل</div>'
                    '<div>لا تُفعّل المحادثة إلا مع مرشح خاص يملك تقرير تقييم حديثاً وصالحاً، '
                    'اجتاز الفحوص الآلية والمراجعة الدلالية دون رفض حالة حرجة.</div></div>'
                )
                gr.JSON(_initial_status, label="حالة نسخة المشروع")
                gr.Markdown(
                    "بيانات Space المحلية قد تضيع عند إعادة التشغيل. تُرسل أمثلة التدريب إلى مستودع "
                    "Dataset خاص عبر `HF_WRITE_TOKEN`. لا يُعدّ ظهور المساحة دليلاً على جاهزية النموذج."
                )
            with gr.Tab("الأخطاء"):
                error_snapshot = gr.JSON(get_error_snapshot(), label="أخطاء الخادم الأخيرة")
                refresh_errors = gr.Button("تحديث سجل الأخطاء")
                refresh_errors.click(get_error_snapshot, outputs=error_snapshot)
                gr.Markdown(
                    "يعرض هذا السجل أخطاء الخادم 5xx فقط، من دون نصوص المحادثات أو بيانات الاعتماد. "
                    "السجل مؤقت في ذاكرة Space؛ لا يضمن الاحتفاظ به بعد إعادة التشغيل أو الخمول."
                )

def launch_app() -> None:
    """Start the UI and JSON API together through Gradio's ZeroGPU-aware server."""
    demo.launch(
        _app=api,
        server_name="0.0.0.0",
        server_port=int(os.getenv("PORT", "7860")),
        show_error=False,
    )


if __name__ == "__main__":
    launch_app()
