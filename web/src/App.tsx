import { Route, Routes } from "react-router";
import LoginPage from "./auth/LoginPage";
import { RequireAuth } from "./auth/RequireAuth";
import HomePage from "./home/HomePage";
import { Layout } from "./layout/Layout";

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route
        path="/*"
        element={
          <RequireAuth>
            <Layout>
              <AuthedRoutes />
            </Layout>
          </RequireAuth>
        }
      />
    </Routes>
  );
}

function AuthedRoutes() {
  return (
    <Routes>
      <Route index element={<HomePage />} />
      <Route path="*" element={<p>Page not found.</p>} />
    </Routes>
  );
}
