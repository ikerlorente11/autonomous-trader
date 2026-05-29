from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Path
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from backend.api.deps import get_session
from backend.api.schemas import (
    CashMovement as CashMovementSchema,
    CashMovementCreate,
    Portfolio as PortfolioSchema,
    PortfolioCreate,
    PortfolioRename,
)
from backend.db.queries.portfolio_queries import (
    add_cash_movement,
    compute_cash,
    count_portfolios,
    create_portfolio,
    delete_portfolio,
    get_cash_movements,
    get_portfolio,
    list_portfolios,
    rename_portfolio,
)

router = APIRouter(prefix="/api/portfolios", tags=["portfolios"])


def _to_schema(portfolio) -> PortfolioSchema:
    return PortfolioSchema(
        id=portfolio.id,
        name=portfolio.name,
        active=portfolio.active,
        created_at=portfolio.created_at,
    )


def _movement_to_schema(movement) -> CashMovementSchema:
    return CashMovementSchema(
        id=movement.id,
        portfolio_id=movement.portfolio_id,
        kind=movement.kind,
        amount=movement.amount,
        ts=movement.ts,
        note=movement.note,
    )


@router.get("", response_model=list[PortfolioSchema])
async def list_all(
    session: AsyncSession = Depends(get_session),
) -> list[PortfolioSchema]:
    return [_to_schema(p) for p in await list_portfolios(session)]


@router.post("", response_model=PortfolioSchema, status_code=201)
async def create(
    payload: PortfolioCreate,
    session: AsyncSession = Depends(get_session),
) -> PortfolioSchema:
    try:
        portfolio = await create_portfolio(
            session, payload.name, payload.initial_deposit
        )
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise HTTPException(
            status_code=409, detail=f"a portfolio named {payload.name!r} already exists"
        ) from None
    return _to_schema(portfolio)


@router.patch("/{portfolio_id}", response_model=PortfolioSchema)
async def rename(
    payload: PortfolioRename,
    portfolio_id: int = Path(...),
    session: AsyncSession = Depends(get_session),
) -> PortfolioSchema:
    try:
        portfolio = await rename_portfolio(session, portfolio_id, payload.name)
        if portfolio is None:
            raise HTTPException(status_code=404, detail="portfolio not found")
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise HTTPException(
            status_code=409, detail=f"a portfolio named {payload.name!r} already exists"
        ) from None
    return _to_schema(portfolio)


@router.delete("/{portfolio_id}")
async def delete(
    portfolio_id: int = Path(...),
    session: AsyncSession = Depends(get_session),
) -> dict[str, int | str]:
    if await count_portfolios(session) <= 1:
        raise HTTPException(
            status_code=409, detail="cannot delete the last remaining portfolio"
        )
    removed = await delete_portfolio(session, portfolio_id)
    if not removed:
        raise HTTPException(status_code=404, detail="portfolio not found")
    await session.commit()
    return {"status": "deleted", "id": portfolio_id}


@router.post(
    "/{portfolio_id}/deposit", response_model=CashMovementSchema, status_code=201
)
async def deposit(
    payload: CashMovementCreate,
    portfolio_id: int = Path(...),
    session: AsyncSession = Depends(get_session),
) -> CashMovementSchema:
    if await get_portfolio(session, portfolio_id) is None:
        raise HTTPException(status_code=404, detail="portfolio not found")
    movement = await add_cash_movement(
        session, portfolio_id, "deposit", payload.amount, note=payload.note
    )
    await session.commit()
    return _movement_to_schema(movement)


@router.post(
    "/{portfolio_id}/withdraw", response_model=CashMovementSchema, status_code=201
)
async def withdraw(
    payload: CashMovementCreate,
    portfolio_id: int = Path(...),
    session: AsyncSession = Depends(get_session),
) -> CashMovementSchema:
    if await get_portfolio(session, portfolio_id) is None:
        raise HTTPException(status_code=404, detail="portfolio not found")
    cash = await compute_cash(session, portfolio_id)
    if payload.amount > cash:
        raise HTTPException(
            status_code=400,
            detail=f"cannot withdraw {payload.amount}; available cash is {cash}",
        )
    movement = await add_cash_movement(
        session, portfolio_id, "withdrawal", payload.amount, note=payload.note
    )
    await session.commit()
    return _movement_to_schema(movement)


@router.get("/{portfolio_id}/movements", response_model=list[CashMovementSchema])
async def movements(
    portfolio_id: int = Path(...),
    session: AsyncSession = Depends(get_session),
) -> list[CashMovementSchema]:
    if await get_portfolio(session, portfolio_id) is None:
        raise HTTPException(status_code=404, detail="portfolio not found")
    return [_movement_to_schema(m) for m in await get_cash_movements(session, portfolio_id)]
