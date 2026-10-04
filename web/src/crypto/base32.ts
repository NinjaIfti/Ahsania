export const CROCKFORD = "0123456789ABCDEFGHJKMNPQRSTVWXYZ";

export function encodeCrockford(bytes: Uint8Array): string {
  let bits = 0;
  let value = 0;
  let out = "";
  for (const byte of bytes) {
    value = (value << 8) | byte;
    bits += 8;
    while (bits >= 5) {
      out += CROCKFORD[(value >>> (bits - 5)) & 31];
      bits -= 5;
    }
    value &= (1 << bits) - 1;
  }
  if (bits > 0) out += CROCKFORD[(value << (5 - bits)) & 31];
  return out;
}

export function decodeCrockford(text: string, byteLength: number) {
  const clean = text.toUpperCase().replace(/[\s-]/g, "").replace(/[IL]/g, "1").replace(/O/g, "0");
  const expectedChars = Math.ceil((byteLength * 8) / 5);
  if (clean.length !== expectedChars) throw new Error(`The key must be ${expectedChars} characters (ignoring dashes)`);
  const out = new Uint8Array(byteLength);
  let bits = 0;
  let value = 0;
  let index = 0;
  for (const ch of clean) {
    const digit = CROCKFORD.indexOf(ch);
    if (digit < 0) throw new Error(`Invalid character "${ch}" in key`);
    value = (value << 5) | digit;
    bits += 5;
    if (bits >= 8) {
      if (index < byteLength) out[index++] = (value >>> (bits - 8)) & 255;
      bits -= 8;
      value &= (1 << bits) - 1;
    }
  }
  return out;
}
