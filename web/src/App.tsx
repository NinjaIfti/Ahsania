import { Route, Routes } from "react-router";
import RecordPage from "./records/RecordPage";
import LoginPage from "./auth/LoginPage";
import { RequireAuth } from "./auth/RequireAuth";
import CapturePage from "./capture/CapturePage";
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
      <Route path="capture" element={<CapturePage />} />
      <Route path="records/:id" element={<RecordPage />} />
      <Route path="records" element={<p>All records — coming next.</p>} />
      <Route path="accounts" element={<p>Accounts — coming next.</p>} />
      <Route path="*" element={<p>Page not found.</p>} />
    </Routes>
  );
}
