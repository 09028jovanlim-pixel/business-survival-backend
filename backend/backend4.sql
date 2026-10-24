SELECT
  batch_number,
  quantity,
  expiry_date
FROM public.inventory
WHERE sku = 'TEST-MILK'
ORDER BY expiry_date;
