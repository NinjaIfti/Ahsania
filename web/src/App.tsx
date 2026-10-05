import { Route, Routes } from "react-router";
import RecordPage from "./records/RecordPage";
import LoginPage from "./auth/LoginPage";
import { RequireAuth } from "./auth/RequireAuth";
import CapturePage from "./capture/CapturePage";
import ReuploadPage from "./capture/ReuploadPage";
import DeviceSetupPage from "./device/DeviceSetupPage";
import HomePage from "./home/HomePage";
import QueuePage from "./queues/QueuePage";
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
      <Route path="setup" element={<DeviceSetupPage />} />
      <Route path="capture" element={<CapturePage />} />
      <Route path="records/:id" element={<RecordPage />} />
      <Route path="records/:id/reupload" element={<ReuploadPage />} />
      <Route path="queue/:stage" element={<QueuePage />} />
      <Route path="*" element={<p>Page not found.</p>} />
    </Routes>
  );
}
