import { Router, type IRouter } from "express";
import {
  GetCapitalAccountResponse,
  GetCapitalMarketsQueryParams,
  GetCapitalMarketsResponse,
} from "@workspace/api-zod";
import { capitalReadOnlyClient } from "../lib/capital-client";

const router: IRouter = Router();

router.get("/trading/capital/account", async (_req, res): Promise<void> => {
  const snapshot = await capitalReadOnlyClient.getAccountSnapshot();
  res.json(GetCapitalAccountResponse.parse(snapshot));
});

router.get("/trading/capital/markets", async (req, res): Promise<void> => {
  const parsed = GetCapitalMarketsQueryParams.safeParse(req.query);
  if (!parsed.success) {
    res.status(400).json({ error: "عبارة البحث عن السوق غير صالحة." });
    return;
  }
  const snapshot = await capitalReadOnlyClient.searchMarkets(parsed.data.searchTerm ?? "");
  res.json(GetCapitalMarketsResponse.parse(snapshot));
});

export default router;
