import express, { type Express, type NextFunction, type Request, type Response } from "express";
import cors from "cors";
import pinoHttp from "pino-http";
import router from "./routes";
import { logger } from "./lib/logger";
import { captureApiErrors } from "./lib/error-events";

const app: Express = express();

app.use(
  pinoHttp({
    logger,
    serializers: {
      req(req) {
        return {
          id: req.id,
          method: req.method,
          url: req.url?.split("?")[0],
        };
      },
      res(res) {
        return {
          statusCode: res.statusCode,
        };
      },
    },
  }),
);
app.use(cors());
app.use(captureApiErrors);
app.use(express.json());
app.use(express.urlencoded({ extended: true }));

app.use("/api", router);

app.use((_req, res) => {
  res.status(404).json({ error: "المسار غير موجود." });
});

app.use((error: unknown, req: Request, res: Response, next: NextFunction) => {
  const candidate =
    error && typeof error === "object"
      ? (error as { status?: unknown; statusCode?: unknown })
      : {};
  const suppliedStatus = Number(candidate.statusCode ?? candidate.status);
  const statusCode =
    Number.isInteger(suppliedStatus) && suppliedStatus >= 400 && suppliedStatus <= 599
      ? suppliedStatus
      : 500;
  const requestId = req.id == null ? null : String(req.id);
  req.log.error(
    {
      statusCode,
      requestId,
      errorType: error instanceof Error ? error.name : "UnknownError",
    },
    "Unhandled API request error",
  );
  if (res.headersSent) {
    next(error);
    return;
  }
  res.status(statusCode).json({
    error: statusCode >= 500 ? "حدث خطأ داخلي غير متوقع." : "تعذر تحليل الطلب.",
    requestId,
  });
});

export default app;
