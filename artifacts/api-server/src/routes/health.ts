import { Router, type IRouter } from "express";
import { GetSystemDiagnosticsResponse, HealthCheckResponse } from "@workspace/api-zod";
import { getSystemDiagnostics } from "../lib/error-events";

const router: IRouter = Router();

router.get("/healthz", (_req, res) => {
  const data = HealthCheckResponse.parse({ status: "ok" });
  res.json(data);
});

router.get("/system/diagnostics", (_req, res) => {
  res.json(GetSystemDiagnosticsResponse.parse(getSystemDiagnostics()));
});

export default router;
