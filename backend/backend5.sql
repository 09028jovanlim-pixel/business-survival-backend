SELECT
  sku,
  batch_number,
  quantity,
  expiry_date
FROM public.inventory
WHERE sku = 'TEST-RACE';
