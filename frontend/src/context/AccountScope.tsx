/**
 * AccountScopeProvider — React context holding the currently-scoped account id.
 */
import React, { createContext, useContext, useState, useEffect, ReactNode } from "react";
import { api, Account } from "../api/client";

interface AccountScopeContextValue {
  accountId: number | null;
  setAccountId: (id: number) => void;
  accounts: Account[];
  activeAccount: Account | null;
  loading: boolean;
  reload: () => void;
}

const AccountScopeContext = createContext<AccountScopeContextValue>({
  accountId: null,
  setAccountId: () => {},
  accounts: [],
  activeAccount: null,
  loading: true,
  reload: () => {},
});

export function AccountScopeProvider({ children }: { children: ReactNode }) {
  const [accounts, setAccounts] = useState<Account[]>([]);
  const [accountId, setAccountId] = useState<number | null>(null);
  const [loading, setLoading] = useState(true);

  const load = async () => {
    setLoading(true);
    try {
      const list = await api.listAccounts();
      setAccounts(list);
      const active = list.find((a) => a.status === "active");
      if (active && accountId === null) {
        setAccountId(active.id);
      }
    } catch {
      // silent — banner will show stale state
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
    const interval = setInterval(load, 30_000);
    return () => clearInterval(interval);
  }, []);

  const activeAccount = accounts.find((a) => a.status === "active") ?? null;

  return (
    <AccountScopeContext.Provider
      value={{ accountId, setAccountId, accounts, activeAccount, loading, reload: load }}
    >
      {children}
    </AccountScopeContext.Provider>
  );
}

export function useAccountScope() {
  return useContext(AccountScopeContext);
}
