import { Router, type IRouter } from "express";
import healthRouter from "./health";
import capitalRouter from "./capital";
import tradingRouter from "./trading";

const router: IRouter = Router();

router.use(healthRouter);
router.use(capitalRouter);
router.use(tradingRouter);

export default router;
