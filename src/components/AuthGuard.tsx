/**
 * Auth Guard — protects routes that require authentication.
 * Redirects to /login/ if no valid token.
 *
 * 2026-09-13（KB-030）：一定要訂閱 AuthContext。
 * logout() 只係 clearAuth() + setUser(null)，**冇 navigate** —— 之前呢個
 * component 只讀 localStorage，唔消費 context，React 見 children 係同一個
 * element reference 就 bail out → 登出之後唔 re-render → 停留喺已登入頁
 * （底部 nav「登出」撳咗冇反應）。訂閱 user 之後 setUser(null) 會令呢度
 * 重新 render，跟住 redirect。
 */

import { Navigate, useLocation } from 'react-router-dom';
import { isAuthenticated } from '../lib/api';
import { useAuth } from '../lib/AuthContext';

interface AuthGuardProps {
  children: React.ReactNode;
}

export default function AuthGuard({ children }: AuthGuardProps) {
  const location = useLocation();
  const { user, loading } = useAuth();

  // Session restore 未跑完（/auth/me 未返）但 token 仍然有效 → 唔好搶先
  // redirect，否則開 app 一瞬間會閃去 /sign-in。冇 token 就照樣即刻 redirect
  // （唔會出現「閃一閃 dashboard」）。
  if (loading && isAuthenticated()) return <>{children}</>;

  if (!isAuthenticated() || !user) {
    return <Navigate to="/sign-in" state={{ from: location.pathname }} replace />;
  }

  return <>{children}</>;
}
