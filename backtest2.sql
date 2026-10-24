ELECT
  has_function_privilege(
    'anon',
    'public.bs_record_transaction(jsonb,uuid)',
    'EXECUTE'
  ) AS anonymous_can_execute,

  has_function_privilege(
    'authenticated',
    'public.bs_record_transaction(jsonb,uuid)',
    'EXECUTE'
  ) AS signed_in_users_can_execute,

  has_function_privilege(
    'service_role',
    'public.bs_record_transaction(jsonb,uuid)',
    'EXECUTE'
  ) AS backend_can_execute;
