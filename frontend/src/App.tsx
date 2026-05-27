/**
 * App — router + layout.
 * Routes: / → /dashboard/daily, /dashboard/daily, /dashboard/weekly,
 *         /accounts, /accounts/:id, /backtests, /settings
 */
import React from "react";
import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import { AccountScopeProvider } from "./context/AccountScope";
import { Layout } from "./components/Layout";
import { Daily } from "./pages/Daily";
import { Weekly } from "./pages/Weekly";
import { Accounts } from "./pages/Accounts";
import { AccountDetail } from "./pages/AccountDetail";
import { Backtests } from "./pages/Backtests";
import { Settings } from "./pages/Settings";

export default function App() {
  return (
    <BrowserRouter>
      <AccountScopeProvider>
        <Layout>
          <Routes>
            <Route path="/" element={<Navigate to="/dashboard/daily" replace />} />
            <Route path="/dashboard/daily" element={<Daily />} />
            <Route path="/dashboard/weekly" element={<Weekly />} />
            <Route path="/accounts" element={<Accounts />} />
            <Route path="/accounts/:id" element={<AccountDetail />} />
            <Route path="/backtests" element={<Backtests />} />
            <Route path="/settings" element={<Settings />} />
          </Routes>
        </Layout>
      </AccountScopeProvider>
    </BrowserRouter>
  );
}
