// Proof-of-work in a Web Worker: find counter with SHA-256(`${nonce}:${counter}`) having >= bits leading zero bits.
self.onmessage = async ({ data: { nonce, bits } }) => {
  const enc = new TextEncoder();
  for (let c = 0; ; c++) {
    const h = new Uint8Array(await crypto.subtle.digest('SHA-256', enc.encode(`${nonce}:${c}`)));
    let z = 0;
    for (const b of h) { if (b === 0) { z += 8; continue; } z += Math.clz32(b) - 24; break; }
    if (z >= bits) { self.postMessage({ counter: c }); return; }
  }
};
