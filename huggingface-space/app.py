from __future__ import annotations

import hmac
import io
import json
import os
import time
import uuid
from datetime import datetime, timezone
from typing import Any

import gradio as gr
import spaces
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
    PROJECT_MODEL_REVISION,
    SAFETY_SYSTEM_PROMPT,
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


@spaces.GPU(duration=240)
def evaluate_candidate_responses(
    candidate_model_id: str,
    candidate_revision: str,
) -> dict[str, dict[str, str]]:
    """Run candidate evaluation through the entrypoint's ZeroGPU wrapper."""
    return _evaluate_candidate_responses(candidate_model_id, candidate_revision)


@spaces.GPU(duration=240)
def train_candidate(uploaded_jsonl: str | None = None) -> str:
    """Run LoRA candidate training through the entrypoint's ZeroGPU wrapper."""
    return _train_candidate(uploaded_jsonl)


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


api = FastAPI(title="Mersad project-trained model API")


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
    result = generate(messages, max_new_tokens=512, temperature=0.2)
    reply = result["content"] or "لم يُرجع النموذج نصاً."
    updated = previous + [
        {"role": "user", "content": message.strip()},
        {"role": "assistant", "content": reply},
    ]
    return "", updated, updated, message.strip(), reply


def _save_correction(prompt: str, correction: str) -> str:
    if not prompt.strip() or not correction.strip():
        raise gr.Error("أرسل سؤالاً أولاً ثم اكتب الإجابة المصححة.")
    try:
        path = save_correction(prompt, correction)
    except Exception as error:
        raise gr.Error(str(error)) from error
    return f"حُفظ مثال التصحيح الخاص: {path}. لن يبدأ التدريب تلقائياً."


def _train(uploaded_jsonl: str | None) -> str:
    try:
        return train_candidate(uploaded_jsonl)
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


def _evaluate_candidate(
    candidate_model_id: str,
) -> tuple[dict[str, Any], str, list[list[str]], list[list[str]], dict[str, Any]]:
    candidate_model_id = candidate_model_id.strip()
    candidate_prefix = os.getenv("CANDIDATE_MODEL_REPO_PREFIX", "").strip().rstrip("/")
    write_token = os.getenv("HF_WRITE_TOKEN") or os.getenv("HF_TOKEN")
    if not candidate_prefix or not candidate_model_id.startswith(f"{candidate_prefix}-candidate-"):
        raise gr.Error("أدخل معرف مرشح أنشأه تدريب مرصاد ضمن بادئة المستودع المضبوطة.")
    if not PROJECT_MODEL_ID:
        raise gr.Error("اضبط PROJECT_MODEL_ID الحالي أولاً كي تتم مقارنة المرشح بالنموذج الحالي.")
    if candidate_model_id == PROJECT_MODEL_ID:
        raise gr.Error("يجب أن يكون المرشح مختلفاً عن النموذج الحالي.")
    if not write_token:
        raise gr.Error("يلزم HF_WRITE_TOKEN لحفظ تقرير التقييم في مستودع المرشح الخاص.")

    try:
        api_client = HfApi(token=write_token)
        candidate_info = api_client.model_info(candidate_model_id, files_metadata=True)
        candidate_fingerprint = model_artifact_fingerprint(candidate_info)
        if not candidate_info.sha or not candidate_fingerprint:
            raise RuntimeError("تعذر تثبيت إصدار ملفات المرشح.")
        responses = evaluate_candidate_responses(candidate_model_id, candidate_info.sha)
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
            "baseline_model_id": PROJECT_MODEL_ID,
            "baseline_revision": PROJECT_MODEL_REVISION,
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
) -> tuple[dict[str, Any], str, list[list[str]], list[list[str]], dict[str, Any]]:
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
        raise gr.Error("سجّل الدخول إلى Hugging Face بحساب مخوّل لحفظ المراجعة.")
    allowed_usernames = {
        name.strip().casefold()
        for name in os.getenv("SEMANTIC_REVIEWER_USERNAMES", "").split(",")
        if name.strip()
    }
    if not allowed_usernames:
        raise gr.Error("لم تُضبط قائمة حسابات المراجعين المصرّح لهم في إعدادات Space.")
    if username.strip().casefold() not in allowed_usernames:
        raise gr.Error("حساب Hugging Face هذا غير مخوّل لمراجعة المرشحين.")
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


with gr.Blocks(title="مرصاد | نموذج المشروع") as demo:
    gr.Markdown(
        "# مرصاد — نموذج المشروع\n"
        "يستخدم هذا الـSpace نسخة مرصاد المدرّبة فقط. لا يوجد نموذج سحابي احتياطي؛ "
        "قبل إنشاء النسخة المدرّبة ستبقى المحادثة مقفلة."
    )
    with gr.Tab("المحادثة"):
        chatbot = gr.Chatbot(height=480, label="محادثة النموذج")
        history_state = gr.State([])
        last_prompt = gr.State("")
        last_reply = gr.State("")
        message = gr.Textbox(
            label="رسالتك",
            placeholder="اكتب رسالتك بالعربية…",
            max_lines=5,
        )
        send = gr.Button("إرسال", variant="primary")
        correction = gr.Textbox(
            label="إجابة مصححة (اختياري)",
            placeholder="اكتب التصحيح الذي توافق على استخدامه في تدريب لاحق.",
            lines=4,
        )
        save_button = gr.Button("حفظ التصحيح للتدريب اللاحق")
        feedback_status = gr.Markdown()
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
            "لا تحفظ كلمات مرور أو مفاتيح أو بيانات حسابات في المحادثة أو التصحيحات. "
            "لا يُحفظ للتدريب إلا التصحيح الذي ترسله صراحةً."
        )
    with gr.Tab("مختبر التداول الكمي"):
        gr.Markdown(
            "هذا المختبر يجلب الأسعار التاريخية مباشرةً من واجهة Capital.com التجريبية، "
            "ويحسب المؤشرات ومرشح MLP متعدد الطبقات ووكيل Q-learning واختباراً خارج العينة. "
            "لا توجد أسعار اصطناعية. ZigZag للعرض الاستعادي ولا يدخل في الإشارات لتجنب تسرب المستقبل؛ "
            "لا يعمل تداول آلي في الخلفية، والتداول الحقيقي مقفل دائماً."
        )
        with gr.Row():
            quant_epic = gr.Textbox(label="Epic للسوق", placeholder="أدخل رمزاً من Capital.com")
            quant_resolution = gr.Dropdown(
                choices=["MINUTE_5", "MINUTE_15", "MINUTE_30", "HOUR", "HOUR_4", "DAY"],
                value="HOUR",
                label="الإطار الزمني",
            )
            quant_count = gr.Slider(minimum=100, maximum=1000, step=100, value=500, label="عدد الشموع")
        fetch_quant_button = gr.Button("جلب بيانات حقيقية", variant="primary")
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
                "وتفعيل `CAPITAL_DEMO_EXECUTION_ENABLED`. يجب التحقق يدوياً من معامل العقد "
                "في تفاصيل السوق؛ لا يُنشأ أمر تلقائي أو حي."
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
            "ملاحظة التشغيل: مساحة Hugging Face المجانية قد تدخل في الخمول؛ لذلك لا يمكن ضمان "
            "تشغيل دائم أو تنفيذ على مدار الساعة. تُحفظ الشموع والتقارير في SQLite محلي، "
            "لكن ملفات المساحة المجانية ليست نسخة احتياطية دائمة."
        )
    with gr.Tab("التدريب"):
        gr.Markdown(
            "يرفع هذا الزر مرشح LoRA قصير التدريب إلى مستودع خاص. "
            "يستخدم Qwen3-8B كأساس للتدريب فقط؛ لا يُستخدم الأساس للرد على المحادثة. "
            "لا يُرقّى المرشح تلقائياً، ويلزم تقييم مستقل قبل تفعيله."
        )
        training_file = gr.File(
            label="ملف أمثلة JSONL اختياري",
            file_types=[".jsonl"],
            type="filepath",
        )
        train_button = gr.Button("إنشاء مرشح تدريب قصير", variant="primary")
        training_status = gr.Markdown()
        train_button.click(_train, inputs=training_file, outputs=training_status)
    with gr.Tab("التقييم والترقية"):
        gr.Markdown(
            "شغّل مجموعة التقييم العربية الثابتة على المرشح والنموذج الحالي. "
            "بعد التقييم راجع كل إجابة دلالياً وفق الإرشادات المحددة، وسجّل القبول أو الرفض. "
            "تُسجّل هوية حساب Hugging Face الموثق تلقائياً؛ أي حالة حرجة مرفوضة أو غير مراجعة تمنع الترقية. "
            "يُحفظ التقرير والمراجعة في مستودع المرشح الخاص. اجتياز التقييم لا يفعّل النموذج؛ "
            "تغيير `PROJECT_MODEL_ID` يبقى خطوة يدوية."
        )
        candidate_id = gr.Textbox(
            label="معرف مستودع المرشح",
            placeholder="owner/model-candidate-…",
        )
        evaluate_button = gr.Button("تقييم المرشح وحفظ التقرير", variant="primary")
        restore_button = gr.Button("تحميل التقييم المعلّق المحفوظ")
        evaluation_report = gr.JSON(label="تقرير التقييم")
        evaluation_status = gr.Markdown()
        gr.Markdown(
            "يلزم تسجيل الدخول إلى Hugging Face باستخدام حساب موجود في قائمة "
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
            outputs=[
                evaluation_report,
                evaluation_status,
                prompt_review_table,
                semantic_reviews,
                evaluation_state,
            ],
        )
        restore_button.click(
            _load_pending_evaluation_report,
            inputs=candidate_id,
            outputs=[
                evaluation_report,
                evaluation_status,
                prompt_review_table,
                semantic_reviews,
                evaluation_state,
            ],
        )
        save_review_button.click(
            _save_semantic_review,
            inputs=[candidate_id, semantic_reviews, evaluation_state],
            outputs=[
                evaluation_report,
                evaluation_status,
                prompt_review_table,
                semantic_reviews,
                evaluation_state,
            ],
        )
    with gr.Tab("الحالة"):
        status = model_status()
        gr.JSON(status, label="حالة النموذج")
        gr.Markdown(
            "نسخة المحادثة لا تُفعّل إلا عند ضبط PROJECT_MODEL_ID على مرشح خاص "
            "يملك تقرير تقييم حديثاً صالحاً اجتاز الفحوص الآلية والمراجعة الدلالية "
            "دون رفض حالة حرجة. "
            "البيانات المحفوظة محلياً في Space قد تضيع عند إعادة التشغيل؛ أمثلة التدريب تُرسل "
            "إلى مستودع Dataset خاص عبر HF_WRITE_TOKEN."
        )
    with gr.Tab("الأخطاء"):
        error_snapshot = gr.JSON(get_error_snapshot(), label="أخطاء الخادم الأخيرة")
        refresh_errors = gr.Button("تحديث سجل الأخطاء")
        refresh_errors.click(get_error_snapshot, outputs=error_snapshot)
        gr.Markdown(
            "يعرض هذا السجل أخطاء الخادم 5xx فقط، من دون نصوص المحادثات أو بيانات الاعتماد. "
            "السجل مؤقت في ذاكرة Space؛ لا يضمن الاحتفاظ به بعد إعادة التشغيل أو الخمول."
        )

app = gr.mount_gradio_app(api, demo, path="/")

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", "7860")))
