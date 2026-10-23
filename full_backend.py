import calendar
import logging
import os
import time
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta
from decimal import Decimal
from functools import lru_cache
from pathlib import Path
from typing import Literal
from uuid import UUID
from zoneinfo import ZoneInfo

from dotenv import load_dotenv
import httpx
from fastapi import APIRouter, Depends, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from postgrest.exceptions import APIError
from pydantic import BaseModel, ConfigDict, Field
from supabase import create_client
from supabase.client import ClientOptions


load_dotenv(Path(__file__).with_name(".env"))

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

bearer = HTTPBearer(auto_error=False)


# ---------------------------------------------------------
# Supabase connection and authentication
# ---------------------------------------------------------

class ResilientSupabaseHTTPClient(httpx.Client):
    """Retry safe reads, including response-body failures, at most twice."""

    def send(self, request, **kwargs):
        # RPCs can change data even when invoked using GET. Never replay them.
        safe_read = (request.method in {"GET", "HEAD"}
                     and "/rpc/" not in request.url.path
                     and not kwargs.get("stream", False))
        attempts = 3 if safe_read else 1
        for attempt in range(attempts):
            try:
                return super().send(request, **kwargs)
            except (httpx.ConnectError, httpx.ConnectTimeout, httpx.ReadError,
                    httpx.ReadTimeout, httpx.RemoteProtocolError) as error:
                if attempt == attempts - 1:
                    raise
                # Do not log URLs, tokens, headers, payloads or customer data.
                logger.warning("Supabase read retry %s/2 (%s)",
                               attempt + 1, type(error).__name__)
                time.sleep(0.25 * (2 ** attempt))


@lru_cache(maxsize=1)
def supabase_http_client():
    return ResilientSupabaseHTTPClient(
        http2=False,
        timeout=httpx.Timeout(20.0, connect=5.0, pool=5.0),
        limits=httpx.Limits(max_connections=10, max_keepalive_connections=5,
                            keepalive_expiry=5.0),
    )


@lru_cache(maxsize=1)
def database():
    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_SECRET_KEY")

    if not url or not key:
        raise HTTPException(
            503,
            "Set SUPABASE_URL and SUPABASE_SECRET_KEY in server secrets.",
        )

    return create_client(url.strip(), key.strip(), options=ClientOptions(
        httpx_client=supabase_http_client(),
        auto_refresh_token=False,
        persist_session=False,
    ))


def staff(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
):
    if not credentials:
        raise HTTPException(
            401,
            "Sign in with Supabase first.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    allowed = {
        value.strip()
        for value in os.getenv("APP_ALLOWED_USER_IDS", "").split(",")
        if value.strip()
    }

    if not allowed:
        raise HTTPException(
            503,
            "Configure APP_ALLOWED_USER_IDS on the backend.",
        )

    client = database()

    try:
        user = client.auth.get_user(credentials.credentials).user
    except httpx.TransportError as error:
        logger.warning("Supabase authentication unavailable (%s)", type(error).__name__)
        raise HTTPException(503, "Authentication service temporarily unavailable.") from None
    except Exception:
        raise HTTPException(
            401,
            "Invalid or expired access token.",
        ) from None

    if not user or str(user.id) not in allowed:
        raise HTTPException(
            403,
            "This account is not an authorized staff member.",
        )

    return str(user.id)


def execute(query):
    try:
        return query.execute().data
    except APIError as error:
        if error.code == "P0001":
            raise HTTPException(409, error.message) from None

        logger.exception("Database request failed")
        raise HTTPException(
            503,
            "Database request failed. Check SQL setup and server logs.",
        ) from None
    except Exception:
        logger.exception("Database unavailable")
        raise HTTPException(503, "Database unavailable.") from None


def all_rows(table, configure=lambda query: query):
    """Read all pages instead of stopping at Supabase's row limit."""
    rows = []

    while True:
        query = configure(database().table(table).select("*"))
        page = execute(
            query.order("id").range(len(rows), len(rows) + 499)
        )

        if not page:
            return rows

        rows.extend(page)


def today():
    return datetime.now(ZoneInfo("Asia/Kuala_Lumpur")).date()


# ---------------------------------------------------------
# Application configuration
# ---------------------------------------------------------

@asynccontextmanager
async def lifespan(app):
    yield
    if supabase_http_client.cache_info().currsize:
        supabase_http_client().close()
    database.cache_clear()
    supabase_http_client.cache_clear()


app = FastAPI(
    title="Business Survival API",
    version="1.0.0",
    lifespan=lifespan,
)

origins = [
    value.strip()
    for value in os.getenv(
        "FRONTEND_ORIGINS",
        "https://business-survival.replit.app",
    ).split(",")
    if value.strip()
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_methods=["GET", "POST", "PUT"],
    allow_headers=["Authorization", "Content-Type"],
)


@app.middleware("http")
async def no_cache(request, call_next):
    response = await call_next(request)
    response.headers["Cache-Control"] = "no-store"
    return response


@app.get("/health")
def health():
    return {"status": "ok"}


api = APIRouter(
    prefix="/api",
    dependencies=[Depends(staff)],
)


# ---------------------------------------------------------
# Inventory calculations
# ---------------------------------------------------------

def eligible_batches(rows, reference_date):
    result = []

    for row in rows:
        if not row.get("expiry_date") or row["quantity"] <= 0:
            continue

        days = (
            date.fromisoformat(row["expiry_date"]) - reference_date
        ).days

        if 0 <= days <= 7:
            result.append(dict(row, days_remaining=days))

    return sorted(
        result,
        key=lambda row: (row["days_remaining"], row["id"]),
    )


def product_summaries(batches):
    grouped = {}

    for batch in batches:
        grouped.setdefault(batch["sku"], []).append(batch)

    result = []

    for sku, items in grouped.items():
        stocked = [item for item in items if item["quantity"] > 0]
        dated = [
            item
            for item in stocked
            if item["days_to_expiry"] is not None
        ]

        nearest = (
            min(dated, key=lambda item: item["days_to_expiry"])
            if dated
            else None
        )
        days = nearest["days_to_expiry"] if nearest else None

        if days is None:
            status = "unknown"
        elif days < 0:
            status = "expired"
        elif days == 0:
            status = "expires_today"
        elif days <= 7:
            status = "expiring"
        else:
            status = "safe"

        eligible = [
            item
            for item in stocked
            if item["days_to_expiry"] is not None
            and 0 <= item["days_to_expiry"] <= 7
        ]
        eligible_ids = {item["id"] for item in eligible}

        if days is None:
            label = "No expiry date" if stocked else "Out of stock"
        elif days < 0:
            label = f"{abs(days)} days overdue"
        elif days == 0:
            label = "Today"
        else:
            label = f"{days} day" + ("" if days == 1 else "s")

        status_labels = {
            "unknown": "No expiry date" if stocked else "Out of stock",
            "expired": "Expired",
            "expires_today": "Expires today",
            "expiring": "Expiring soon",
            "safe": "Safe",
        }

        result.append({
            "sku": sku,
            "product_name": items[0]["product_name"],
            "quantity": sum(item["quantity"] for item in items),
            "batch_count": len(items),
            "expiry_date": nearest["expiry_date"] if nearest else None,
            "days_remaining": days,
            "days_remaining_label": label,
            "status": status,
            "status_label": status_labels[status],
            "expiring_units": sum(
                item["quantity"] for item in eligible
            ),
            "expired_units": sum(
                item["quantity"]
                for item in stocked
                if item["status"] == "expired"
            ),
            "promotion_eligible": bool(eligible),
            "promotion_batch_ids": [
                item["id"] for item in eligible
            ],
            "batches": [
                dict(
                    item,
                    promotion_eligible=item["id"] in eligible_ids,
                )
                for item in items
            ],
        })

    return result


@api.get("/inventory")
def inventory():
    reference_date = today()
    rows = all_rows("inventory")
    batches = []

    for row in rows:
        expiry = row.get("expiry_date")
        days = (
            (date.fromisoformat(expiry) - reference_date).days
            if expiry
            else None
        )

        if days is None:
            status = "unknown"
        elif days < 0:
            status = "expired"
        elif days <= 7:
            status = "expiring"
        else:
            status = "good"

        batches.append(
            dict(row, days_to_expiry=days, status=status)
        )

    candidates = eligible_batches(batches, reference_date)

    return {
        "as_of": reference_date.isoformat(),
        "total_units": sum(row["quantity"] for row in rows),
        "total_products": len({row["sku"] for row in rows}),
        "total_batches": len(rows),
        "expired_batches": sum(
            row["status"] == "expired" for row in batches
        ),
        "expiring_batches": sum(
            row["status"] == "expiring" for row in batches
        ),
        "units_at_risk": sum(
            row["quantity"] for row in candidates
        ),
        "promotion_candidates": candidates,
        "batches": batches,
    }


@api.get("/products")
def products(
    status: Literal[
        "all", "expiring", "expired", "safe", "unknown"
    ] = "all",
    search: str = "",
    sort: Literal[
        "nearest_expiry", "farthest_expiry", "name", "quantity"
    ] = "nearest_expiry",
):
    data = inventory()
    summaries = product_summaries(data["batches"])

    def matches(item, selected):
        if selected == "all":
            return True
        if selected == "expiring":
            return item["expiring_units"] > 0
        if selected == "expired":
            return item["expired_units"] > 0
        return item["status"] == selected

    counts = {
        key: sum(matches(item, key) for item in summaries)
        for key in ("all", "expiring", "expired", "safe", "unknown")
    }

    query = search.strip().casefold()
    visible = []

    for item in summaries:
        values = [
            item["sku"],
            item["product_name"],
            *[batch["batch_number"] for batch in item["batches"]],
        ]

        if matches(item, status) and (
            not query
            or any(query in value.casefold() for value in values)
        ):
            visible.append(item)

    if sort == "name":
        visible.sort(
            key=lambda item: (
                item["product_name"].casefold(),
                item["sku"],
            )
        )
    elif sort == "quantity":
        visible.sort(
            key=lambda item: (-item["quantity"], item["sku"])
        )
    else:
        direction = -1 if sort == "farthest_expiry" else 1
        visible.sort(
            key=lambda item: (
                item["days_remaining"] is None,
                (item["days_remaining"] or 0) * direction,
                item["sku"],
            )
        )

    return {
        "as_of": data["as_of"],
        "counts": counts,
        "total": len(visible),
        "units_at_risk": data["units_at_risk"],
        "products": visible,
    }


# ---------------------------------------------------------
# Financial calculations
# ---------------------------------------------------------

def period_bounds(period, selected, reference_date):
    suffix = {
        "day": "",
        "month": "-01",
        "year": "-01-01",
    }[period]
    anchor = date.fromisoformat(selected + suffix)

    if period == "day":
        start = end = anchor
        previous = anchor - timedelta(days=1)
    elif period == "month":
        start = anchor.replace(day=1)
        end = anchor.replace(
            day=calendar.monthrange(anchor.year, anchor.month)[1]
        )
        previous = (start - timedelta(days=1)).replace(day=1)
    else:
        start = date(anchor.year, 1, 1)
        end = date(anchor.year, 12, 31)
        previous = date(anchor.year - 1, 1, 1)

    effective_end = min(end, reference_date)
    current_period = start <= reference_date <= end

    if period == "month":
        previous_end = previous.replace(
            day=min(
                effective_end.day if current_period else 31,
                calendar.monthrange(
                    previous.year, previous.month
                )[1],
            )
        )
    elif period == "year" and current_period:
        previous_end = date(
            previous.year,
            effective_end.month,
            min(
                effective_end.day,
                calendar.monthrange(
                    previous.year, effective_end.month
                )[1],
            ),
        )
    elif period == "year":
        previous_end = date(previous.year, 12, 31)
    else:
        previous_end = previous

    return start, effective_end, previous, previous_end


def totals(rows):
    revenue = sum(
        (
            Decimal(str(row["amount"]))
            for row in rows
            if row["kind"] == "revenue"
        ),
        Decimal(0),
    )
    expenses = sum(
        (
            Decimal(str(row["amount"]))
            for row in rows
            if row["kind"] == "expense"
        ),
        Decimal(0),
    )

    profit = revenue - expenses

    return {
        "revenue": float(revenue),
        "expenses": float(expenses),
        "net_profit": float(profit),
        "profit_margin": (
            round(float(profit / revenue * 100), 2)
            if revenue
            else None
        ),
    }


class Input(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
    )


class Transaction(Input):
    # Generate once in the frontend and reuse the ID on retries.
    id: UUID
    occurred_on: date
    kind: Literal["revenue", "expense"]
    amount: Decimal = Field(
        gt=0, max_digits=14, decimal_places=2
    )
    category: str = Field(min_length=1, max_length=100)
    description: str = Field(default="", max_length=1000)
    sku: str | None = Field(default=None, max_length=200)
    units: int = Field(
        default=0, strict=True, ge=0, le=2147483647
    )


@api.post("/transactions")
def record_transaction(body: Transaction, user=Depends(staff)):
    return execute(
        database().rpc(
            "bs_record_transaction",
            {
                "payload": body.model_dump(mode="json"),
                "actor": user,
            },
        )
    )


@api.get("/financial-analytics")
def analytics(
    period: Literal["day", "month", "year"] = "month",
    date: str | None = None,
):
    now = today()
    length = {"day": 10, "month": 7, "year": 4}[period]
    selected = date or now.isoformat()[:length]

    try:
        start, end, previous_start, previous_end = period_bounds(
            period, selected, now
        )
    except (ValueError, OverflowError):
        raise HTTPException(
            422,
            "Use YYYY-MM-DD for day, YYYY-MM for month, "
            "or YYYY for year.",
        ) from None

    if start > now:
        raise HTTPException(
            422, "Choose a current or past period."
        )

    rows = all_rows(
        "bs_transactions",
        lambda query: query.gte(
            "occurred_on", previous_start.isoformat()
        ).lte("occurred_on", end.isoformat()),
    )

    current = [
        row
        for row in rows
        if start.isoformat() <= row["occurred_on"] <= end.isoformat()
    ]
    previous = [
        row
        for row in rows
        if previous_start.isoformat()
        <= row["occurred_on"]
        <= previous_end.isoformat()
    ]

    figures = totals(current)
    comparison = totals(previous)

    series = {}
    sales = {}

    for row in current:
        bucket = (
            row["occurred_on"][:7]
            if period == "year"
            else row["occurred_on"]
        )
        series.setdefault(bucket, []).append(row)

        if row["kind"] == "revenue" and row.get("sku"):
            item = sales.setdefault(
                row["sku"],
                {
                    "sku": row["sku"],
                    "units_sold": 0,
                    "revenue": Decimal(0),
                },
            )
            item["units_sold"] += row["units"]
            item["revenue"] += Decimal(str(row["amount"]))

    available = {}
    names = {}

    for row in all_rows("inventory"):
        names[row["sku"]] = row["product_name"]

        if (
            row.get("expiry_date")
            and row["expiry_date"] >= now.isoformat()
        ):
            available[row["sku"]] = (
                available.get(row["sku"], 0) + row["quantity"]
            )

    ranked = sorted(
        [
            dict(
                item,
                revenue=float(item["revenue"]),
                product_name=names.get(item["sku"], item["sku"]),
                remaining_stock=available.get(item["sku"], 0),
            )
            for item in sales.values()
        ],
        key=lambda item: (-item["units_sold"], item["sku"]),
    )

    positive = sorted(
        item["units_sold"]
        for item in ranked
        if item["units_sold"] > 0
    )
    cutoff = (
        positive[max(0, (len(positive) + 3) // 4 - 1)]
        if positive
        else 0
    )

    changes = {
        key: (
            round(
                (figures[key] - comparison[key])
                / abs(comparison[key])
                * 100,
                2,
            )
            if comparison[key]
            else None
        )
        for key in ("revenue", "expenses", "net_profit")
    }

    return {
        "data_source": "supabase",
        "currency": "MYR",
        "period": period,
        "date": selected,
        "start": start,
        "end": end,
        "comparison_start": previous_start,
        "comparison_end": previous_end,
        **figures,
        "previous": comparison,
        "change_percent": changes,
        "series": [
            dict(date=bucket, **totals(items))
            for bucket, items in sorted(series.items())
        ],
        "best_selling_products": ranked[:5],
        "slow_selling_products": [
            item
            for item in ranked
            if 0 < item["units_sold"] <= cutoff
            and item["remaining_stock"] >= 5
        ],
        "low_profit": figures["net_profit"] < float(
            os.getenv("LOW_PROFIT_THRESHOLD", "3500")
        ),
    }


@api.get("/overview")
def overview(
    period: Literal["day", "month", "year"] = "month",
    date: str | None = None,
):
    financial = analytics(period, date)
    stock = inventory()

    return {
        "financial": financial,
        "inventory": stock,
        "expiring_products": stock["promotion_candidates"],
    }


# ---------------------------------------------------------
# Customers and promotions
# ---------------------------------------------------------

@api.get("/customers")
def customers():
    rows = all_rows("bs_customers")

    return {
        "total": len(rows),
        "customers": rows,
        "eligible_count": sum(
            row["subscribed"] for row in rows
        ),
    }


class Selection(Input):
    batch_ids: list[int] = Field(
        min_length=1, max_length=100
    )


class Promotion(Selection):
    id: UUID
    recipient_ids: list[UUID] = Field(
        min_length=1, max_length=1000
    )
    title: str = Field(min_length=1, max_length=200)
    discount_percent: int = Field(
        strict=True, ge=0, le=100
    )
    subject: str = Field(min_length=1, max_length=300)
    message: str = Field(min_length=1, max_length=10000)


@api.post("/promotions/recommendation")
def recommend(body: Selection):
    eligible = eligible_batches(all_rows("inventory"), today())
    chosen = [
        row for row in eligible if row["id"] in body.batch_ids
    ]

    if {row["id"] for row in chosen} != set(body.batch_ids):
        raise HTTPException(
            409,
            "Select available batches expiring today "
            "through 7 days ahead.",
        )

    nearest = min(row["days_remaining"] for row in chosen)
    discount = 25 if nearest <= 1 else 15 if nearest <= 3 else 10
    names = ", ".join(
        sorted({row["product_name"] for row in chosen})
    )
    units = sum(row["quantity"] for row in chosen)

    return {
        "source": "rule_based",
        "discount_percent": discount,
        "title": "Limited-time stock offer",
        "subject": f"Save {discount}% on selected products",
        "message": (
            f"Enjoy {discount}% off {names} "
            "while eligible stock lasts."
        ),
        "reason": (
            f"Nearest batch expires in {nearest} days; "
            f"selected stock totals {units} units."
        ),
        "profitability_verified": False,
        "requires_approval": True,
        "batches": chosen,
    }


@api.post("/promotions")
def save_promotion(body: Promotion, user=Depends(staff)):
    return execute(
        database().rpc(
            "bs_promotion_action",
            {
                "promotion_id": str(body.id),
                "action": "save",
                "payload": body.model_dump(mode="json"),
                "actor": user,
            },
        )
    )


@api.get("/promotions")
def promotions(
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    return execute(
        database()
        .table("bs_promotions")
        .select("*")
        .order("created_at", desc=True)
        .order("id")
        .range(offset, offset + limit - 1)
    )


@api.post("/promotions/{promotion_id}/{action}")
def promotion_action(
    promotion_id: UUID,
    action: Literal["approve", "reject", "simulate"],
    user=Depends(staff),
):
    # The SQL function enforces approval rules, locks the
    # approved snapshot and prevents duplicate final actions.
    # "simulate" never sends real emails or changes inventory.
    return execute(
        database().rpc(
            "bs_promotion_action",
            {
                "promotion_id": str(promotion_id),
                "action": action,
                "payload": {},
                "actor": user,
            },
        )
    )


# ---------------------------------------------------------
# Activity history
# ---------------------------------------------------------

@api.get("/activity-history")
def history(
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    return execute(
        database()
        .table("bs_activity")
        .select("*")
        .order("created_at", desc=True)
        .order("id", desc=True)
        .range(offset, offset + limit - 1)
    )


# Insert this section BEFORE app.include_router(api) in full_backend.py.
# Uses the existing Input, api, staff, database, execute, Field, date, UUID,
# Literal, Query and HTTPException definitions from that file.

class StockReceiptInput(Input):
    id: UUID
    reference: str = Field(min_length=1, max_length=200)
    sku: str = Field(min_length=1, max_length=200)
    quantity: int = Field(strict=True, gt=0, le=2147483647)
    batch_number: str = Field(min_length=1, max_length=200)
    expiry_date: date
    delivery_date: date
    supplier: str = Field(min_length=1, max_length=300)


@api.get('/receiving/receipts')
def receiving_receipts(limit: int = Query(50, ge=1, le=100), offset: int = Query(0, ge=0)):
    rows = execute(
        database().table('bs_stock_receipts').select('*')
        .order('updated_at', desc=True).order('id').range(offset, offset + limit - 1)
    )
    return {'receipts': rows}


@api.post('/receiving/receipts')
def save_receiving_receipt(body: StockReceiptInput, user=Depends(staff)):
    if body.expiry_date < body.delivery_date:
        raise HTTPException(422, 'Expiry cannot be before the delivery date.')
    if body.delivery_date > today():
        raise HTTPException(422, 'Stock cannot be received before its delivery date.')
    return execute(database().rpc('bs_receive_stock', {
        'receipt_id': str(body.id), 'action': 'save',
        'payload': body.model_dump(mode='json', exclude={'id'}), 'actor': user,
    }))


@api.post('/receiving/receipts/{receipt_id}/{action}')
def finalize_receiving_receipt(receipt_id: UUID, action: Literal['approve', 'reject'], user=Depends(staff)):
    # Finalize the stored draft; never trust unsaved browser fields for approval.
    return execute(database().rpc('bs_receive_stock', {
        'receipt_id': str(receipt_id), 'action': action, 'payload': {}, 'actor': user,
    }))


# ---------------------------------------------------------
# Regular product selling prices
# ---------------------------------------------------------

@api.get("/product-prices")
def get_product_prices():
    rows = execute(
        database()
        .table("bs_product_prices")
        .select("sku, regular_selling_price, currency, version")
        .order("sku")
    )
    return {"prices": rows}

# Validate product selling price requests
class ProductPriceInput(Input):
    sku: str = Field(min_length=1, max_length=200)
    regular_selling_price: Decimal = Field(
        gt=0,
        max_digits=12,
        decimal_places=2
    )
    expected_version: int | None = Field(default=None, ge=1)

@api.post("/product-prices")
def save_product_price(
    body: ProductPriceInput,
    user=Depends(staff)
):
    return execute(
        database().rpc(
            "bs_set_product_price",
            {
                "payload": body.model_dump(mode="json"),
                "actor": user,
            },
        )
    )


app.include_router(api)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        app,
        host="0.0.0.0",
        port=int(os.getenv("PORT", "8000")),
    )
