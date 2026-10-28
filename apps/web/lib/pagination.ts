"use client";

import { useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { api, Page } from "./api";

export function usePaginatedQuery<T>(
  key: string,
  path: string,
  options: {
    filters?: Record<string, string>;
    refetchInterval?: number;
  } = {},
) {
  const [page, setPage] = useState(0);
  const [search, setSearch] = useState("");
  const pageSize = 20;
  const params = new URLSearchParams({
    ...options.filters,
    limit: String(pageSize),
    offset: String(page * pageSize),
  });
  if (search.trim()) params.set("q", search.trim());
  const queryString = params.toString();
  const query = useQuery({
    queryKey: [key, queryString],
    queryFn: ({ signal }) =>
      api<Page<T>>(`${path}?${queryString}`, { signal }),
    refetchInterval: options.refetchInterval,
  });
  // Deleting or deciding the last item on a page can shrink the result set.
  const total = query.data?.total;
  useEffect(() => {
    if (total !== undefined) {
      const lastPage = Math.max(0, Math.ceil(total / pageSize) - 1);
      if (page > lastPage) setPage(lastPage);
    }
  }, [page, total]);
  return {
    query,
    pagination: {
      page,
      pageSize,
      total: total ?? 0,
      onPageChange: setPage,
    },
    search: {
      value: search,
      onChange: (value: string) => {
        setSearch(value);
        setPage(0);
      },
    },
    resetPage: () => setPage(0),
  };
}
