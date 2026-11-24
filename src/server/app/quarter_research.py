"""Quarterly research from public company filings."""

from datetime import date
from typing import Annotated

import httpx
from fastapi import APIRouter, HTTPException, Path

from src.server.dependencies.principal import DataReadUserId
from src.server.services.quarter_research import ResearchNotFound, load_quarter

router = APIRouter(prefix="/api/v1/research", tags=["Research"])


@router.get("/quarter/{symbol}")
async def quarter_research(
    symbol: Annotated[str, Path(pattern=r"^[A-Za-z0-9][A-Za-z0-9.-]{0,11}$")],
    user_id: DataReadUserId,
    period: date | None = None,
) -> dict:
    try:
        return await load_quarter(symbol.upper(), period)
    except ResearchNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from None
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 404:
            raise HTTPException(status_code=404, detail="SEC filing data was not found.") from None
        raise HTTPException(status_code=503, detail="SEC EDGAR is temporarily unavailable.") from None
    except (httpx.RequestError, ValueError):
        raise HTTPException(status_code=503, detail="SEC EDGAR is temporarily unavailable.") from None
