from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import User
from app.routers.auth import get_current_user
from app.schemas import OrderCreateRequest, OrderResponse
from app.services.orders import CustomerNotFoundError, InvalidQuantityError, PlanNotFoundError, create_order
from app.services.pricing import PriceNotFoundError

router = APIRouter(prefix="/api/v1", tags=["orders"])


@router.post("/orders", response_model=OrderResponse, status_code=201)
def siparis_olustur(
    body: OrderCreateRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> OrderResponse:
    """`customer_id` oturumdaki kullanıcıdan gelir — eskiden query parametresi
    olarak istemciden alınıyordu, bu da herkesin başkasının customer_id'siyle
    sipariş açabilmesine (IDOR) izin veriyordu."""
    try:
        order = create_order(
            db, customer_id=user.customer_id, plan_id=body.plan_id, months=body.months, quantity=body.quantity
        )
    except CustomerNotFoundError as e:
        raise HTTPException(404, str(e)) from e
    except PlanNotFoundError as e:
        raise HTTPException(404, str(e)) from e
    except PriceNotFoundError as e:
        raise HTTPException(422, str(e)) from e
    except InvalidQuantityError as e:
        raise HTTPException(422, str(e)) from e
    return OrderResponse.model_validate(order)
