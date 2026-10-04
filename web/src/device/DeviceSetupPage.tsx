import { useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { api, json } from "../api/client";
import { useExpectedFingerprint } from "../api/hooks";
import { useCurrentUser } from "../auth/RequireAuth";
import { fingerprintOf, formatKeyForPrint, generateKeyString, importHmacKey } from "../crypto/deviceKey";
import { checkEnteredKey } from "../crypto/keySetup";
import { saveDeviceKey, useDeviceKey } from "../crypto/keyStore";
import { card, inputClass, primaryButton, secondaryButton } from "../ui/styles";

export default function DeviceSetupPage() {
  const me = useCurrentUser();
  const queryClient = useQueryClient();
  const expectedQuery = useExpectedFingerprint(me.role === "hospital_doctor");
  const deviceKey = useDeviceKey();
  const [generated, setGenerated] = useState<string | null>(null);
  const [writtenDown, setWrittenDown] = useState(false);
  const [entered, setEntered] = useState("");
  const [message, setMessage] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  if (me.role !== "hospital_doctor") return <p>Only a hospital doctor can set up this device.</p>;
  if (expectedQuery.isPending || deviceKey.isPending) return <p>Loading…</p>;
  if (expectedQuery.isError) return <p role="alert" className="text-red-700">{expectedQuery.error.message}</p>;
  const expected = expectedQuery.data.expected;

  async function install(canonical: string, fingerprint: string) {
    setBusy(true);
    setMessage(null);
    try {
      await api("/device/fingerprint", { method: "POST", body: json({ fingerprint }) });
      await saveDeviceKey({ cryptoKey: await importHmacKey(canonical), fingerprint });
      setGenerated(null);
      setEntered("");
      await queryClient.invalidateQueries({ queryKey: ["deviceKey"] });
      await queryClient.invalidateQueries({ queryKey: ["fingerprint"] });
      setMessage(`Device ready — key ${fingerprint}`);
    } catch (e) {
      setMessage(e instanceof Error ? e.message : "Setup failed");
    } finally {
      setBusy(false);
    }
  }

  async function applyGenerated() {
    if (generated) await install(generated, await fingerprintOf(generated));
  }

  async function applyEntered() {
    const result = await checkEnteredKey(entered, expected);
    if (!result.ok) {
      setMessage(result.message);
      return;
    }
    await install(result.canonical, result.fingerprint);
  }

  return (
    <section className="space-y-6">
      <h1 className="text-2xl font-semibold">Device setup</h1>
      <p>
        This device: <strong data-testid="device-fingerprint">{deviceKey.data ? deviceKey.data.fingerprint : "no key"}</strong>
      </p>
      <p>
        Hospital key registered on the server: <strong>{expected ?? "none yet"}</strong>
      </p>
      {expected === null ? (
        <div className={`${card} space-y-3`}>
          <h2 className="text-lg font-semibold">First device: create the hospital key</h2>
          <p className="text-sm text-slate-700">
            The key never leaves the hospital. Print or write it down, seal it, and give it to the two key custodians.
            Every other device needs this key.
          </p>
          {generated === null ? (
            <button type="button" onClick={() => setGenerated(generateKeyString())} className={primaryButton}>
              Generate key
            </button>
          ) : (
            <>
              <pre data-testid="generated-key" className="break-all rounded bg-slate-100 p-3 font-mono text-lg">
                {formatKeyForPrint(generated)}
              </pre>
              <label className="flex items-start gap-2">
                <input type="checkbox" checked={writtenDown} onChange={(e) => setWrittenDown(e.target.checked)} className="mt-1" />
                <span>I have written down this key and stored it safely</span>
              </label>
              <button type="button" disabled={!writtenDown || busy} onClick={applyGenerated} className={primaryButton}>
                Use this key on this device
              </button>
            </>
          )}
        </div>
      ) : (
        <div className={`${card} space-y-3`}>
          <h2 className="text-lg font-semibold">Enter the hospital key</h2>
          <label className="block">
            <span className="text-sm font-medium">Hospital key</span>
            <input value={entered} onChange={(e) => setEntered(e.target.value)} placeholder="XXXX-XXXX-…" autoComplete="off" spellCheck={false} className={`${inputClass} font-mono`} />
          </label>
          <button type="button" disabled={busy || !entered.trim()} onClick={applyEntered} className={secondaryButton}>
            Save key on this device
          </button>
        </div>
      )}
      {message && (
        <p role="status" className="rounded-md bg-slate-100 p-3">
          {message}
        </p>
      )}
    </section>
  );
}
