// MAX mini-app целиком клиентский: identity/start_param приходят из Bridge,
// а незавершённый address-flow восстанавливается из localStorage.
// Статика для GitHub Pages (adapter-static + SPA fallback 404.html).
export const ssr = false;
export const prerender = true;
