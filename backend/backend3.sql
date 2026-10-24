
-- BUSINESS SURVIVAL: TEST PROJECT ONLY
-- DO NOT execute on XMUM HACK / production.
-- Requires public.inventory, public.bs_transactions, public.bs_activity,
-- and test inventory containing TEST-MILK / BATCH-A.
-- This is a single-business TEST prototype, NOT a multi-tenant production RPC.
-- Create and inspect the function first. Do not record a sale yet.

BEGIN;

DO $safety$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM public.inventory
    WHERE sku = 'TEST-MILK' AND batch_number = 'BATCH-A'
  ) OR NOT EXISTS (
    SELECT 1 FROM public.inventory
    WHERE sku = 'TEST-MILK' AND batch_number = 'BATCH-B'
  ) OR NOT EXISTS (
    SELECT 1 FROM public.inventory
    WHERE sku = 'TEST-MILK' AND batch_number = 'BATCH-EXPIRED'
  ) THEN
    RAISE EXCEPTION 'TEST ONLY: required TEST-MILK batches not found. Stop; do not run on production.';
  END IF;
END;
$safety$;

CREATE OR REPLACE FUNCTION public.bs_record_transaction(payload jsonb, actor uuid)
RETURNS jsonb
LANGUAGE plpgsql
SET search_path = public, pg_temp
AS $function$
DECLARE
  desired public.bs_transactions%ROWTYPE;
  existing public.bs_transactions%ROWTYPE;
  saved public.bs_transactions%ROWTYPE;
  batch RECORD;
  remaining INTEGER;
  take_units INTEGER;
  local_today DATE := (CURRENT_TIMESTAMP AT TIME ZONE 'Asia/Kuala_Lumpur')::date;
BEGIN
  desired := jsonb_populate_record(NULL::public.bs_transactions, payload);
  desired.units := COALESCE(desired.units, 0);
  desired.description := COALESCE(desired.description, '');

  IF actor IS NULL OR desired.id IS NULL OR desired.occurred_on IS NULL
     OR desired.kind NOT IN ('revenue', 'expense') OR desired.kind IS NULL
     OR desired.amount IS NULL OR desired.amount <= 0
     OR desired.category IS NULL OR btrim(desired.category) = ''
     OR desired.units < 0 THEN
    RAISE EXCEPTION 'Invalid transaction fields';
  END IF;

  IF desired.kind = 'expense' AND
     (desired.sku IS NOT NULL OR desired.units <> 0) THEN
    RAISE EXCEPTION 'An expense cannot include product SKU or sold units';
  END IF;

  IF desired.kind = 'revenue' AND (
      (desired.sku IS NULL AND desired.units <> 0) OR
      (desired.sku IS NOT NULL AND desired.units = 0)
  ) THEN
    RAISE EXCEPTION 'A product sale needs both a SKU and positive sold units';
  END IF;

  -- Serialize same-ID retries.
  PERFORM pg_advisory_xact_lock(
    hashtextextended('transaction:' || desired.id::text, 0)
  );

  SELECT *
  INTO existing
  FROM public.bs_transactions
  WHERE id = desired.id;

  IF FOUND THEN
    IF (
      existing.occurred_on,
      existing.kind,
      existing.amount,
      existing.category,
      existing.description,
      existing.sku,
      existing.units,
      existing.created_by
    ) IS DISTINCT FROM (
      desired.occurred_on,
      desired.kind,
      desired.amount,
      desired.category,
      desired.description,
      desired.sku,
      desired.units,
      actor
    ) THEN
      RAISE EXCEPTION
        'Transaction ID already exists with different values or actor';
    END IF;

    RETURN to_jsonb(existing);
  END IF;

  IF desired.kind = 'revenue' AND desired.sku IS NOT NULL THEN

    -- Serialize sales for the same product.
    PERFORM pg_advisory_xact_lock(
      hashtextextended('product:' || desired.sku, 0)
    );

    remaining := desired.units;

    -- FEFO: earliest unexpired batches first.
    -- NULL expiry dates are not eligible.
    FOR batch IN
      SELECT id, quantity
      FROM public.inventory
      WHERE sku = desired.sku
        AND quantity > 0
        AND expiry_date >= local_today
      ORDER BY expiry_date, id
      FOR UPDATE
    LOOP
      take_units := LEAST(batch.quantity, remaining);

      UPDATE public.inventory
      SET quantity = quantity - take_units
      WHERE id = batch.id
        AND quantity >= take_units;

      IF NOT FOUND THEN
        RAISE EXCEPTION
          'Inventory changed during stock deduction';
      END IF;

      remaining := remaining - take_units;

      EXIT WHEN remaining = 0;
    END LOOP;

    IF remaining > 0 THEN
      RAISE EXCEPTION
        'Insufficient unexpired inventory for SKU %; short by % units',
        desired.sku, remaining;
    END IF;

  END IF;

  INSERT INTO public.bs_transactions
    (
      id,
      occurred_on,
      kind,
      amount,
      category,
      description,
      sku,
      units,
      created_by
    )
  VALUES
    (
      desired.id,
      desired.occurred_on,
      desired.kind,
      desired.amount,
      desired.category,
      desired.description,
      desired.sku,
      desired.units,
      actor
    )
  RETURNING * INTO saved;

  INSERT INTO public.bs_activity
    (action, entity_id, actor)
  VALUES
    ('transaction_recorded', saved.id, actor);

  RETURN to_jsonb(saved);
END;
$function$;

COMMIT;
