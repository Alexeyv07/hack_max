// MAX mini-app целиком клиентский: identity/start_param приходят из Bridge,
// а незавершённый address-flow восстанавливается из localStorage.
// SSR здесь только создаёт промежуточный экран до hydration при reload WebView.
export const ssr = false;
