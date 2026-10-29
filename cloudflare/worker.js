import { Container, getContainer } from "@cloudflare/containers";

// Секреты Worker'а, которые передаются в программу (так же, как переменные окружения на компьютере)
const PASS_THROUGH = ["DATABASE_URL", "WB_API_TOKEN", "WB_PRICES_TOKEN", "MPSTATS_TOKEN"];

export class TorpedaContainer extends Container {
  defaultPort = 8000;
  sleepAfter = "1h";

  constructor(ctx, env) {
    super(ctx, env);
    this.envVars = Object.fromEntries(PASS_THROUGH.filter((k) => env[k]).map((k) => [k, env[k]]));
  }
}

function unauthorized() {
  return new Response("Нужен пароль", {
    status: 401,
    headers: { "WWW-Authenticate": 'Basic realm="Торпеда", charset="UTF-8"' },
  });
}

async function sameSecret(a, b) {
  const enc = new TextEncoder();
  const [ha, hb] = await Promise.all([
    crypto.subtle.digest("SHA-256", enc.encode(a)),
    crypto.subtle.digest("SHA-256", enc.encode(b)),
  ]);
  const [x, y] = [new Uint8Array(ha), new Uint8Array(hb)];
  return x.every((v, i) => v === y[i]);
}

export default {
  async fetch(request, env) {
    // без пароля сайт не открывается вообще: в программе лежат ключи WB и MPSTATS
    if (!env.TORPEDA_PASSWORD) return new Response("Не задан секрет TORPEDA_PASSWORD", { status: 503 });
    const auth = request.headers.get("Authorization") || "";
    let given = "";
    if (auth.startsWith("Basic ")) {
      try {
        const decoded = new TextDecoder().decode(Uint8Array.from(atob(auth.slice(6)), (c) => c.charCodeAt(0)));
        given = decoded.slice(decoded.indexOf(":") + 1);
      } catch {
        return unauthorized();
      }
    }
    if (!given || !(await sameSecret(given, env.TORPEDA_PASSWORD))) return unauthorized();
    return getContainer(env.TORPEDA).fetch(request);
  },
};
