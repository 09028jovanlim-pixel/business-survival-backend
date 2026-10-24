CREATE TABLE public.bs_transactions (
    id UUID PRIMARY KEY,
    occurred_on DATE NOT NULL,
    kind TEXT NOT NULL
        CHECK (kind IN ('revenue', 'expense')),
    amount NUMERIC(14, 2) NOT NULL
        CHECK (amount > 0),
    category TEXT NOT NULL,
    description TEXT DEFAULT '',
    sku TEXT,
    units INTEGER NOT NULL DEFAULT 0
        CHECK (units >= 0),
    created_by UUID,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

ALTER TABLE public.bs_transactions
ENABLE ROW LEVEL SECURITY;
