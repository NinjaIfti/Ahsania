import { Link } from "react-router";
import { useCurrentUser } from "../auth/RequireAuth";
import { isHospital } from "../auth/roles";

export default function HomePage() {
  const me = useCurrentUser();
  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-semibold">Welcome, {me.name}</h1>
      {isHospital(me.role) && (
        <Link to="/capture" className="block rounded-xl bg-blue-700 p-6 text-center text-xl font-semibold text-white hover:bg-blue-800">
          New capture
        </Link>
      )}
    </div>
  );
}
