<script setup lang="ts">
import { RouterLink, RouterView } from "vue-router";

import AppIcon from "@/components/ui/AppIcon.vue";
import ThemeToggle from "@/components/ui/ThemeToggle.vue";
</script>

<template>
  <div class="auth-shell">
    <header class="auth-header">
      <RouterLink class="auth-brand" to="/" aria-label="COPE Chess home">
        <AppIcon name="logo" :size="25" />
        <span>COPE</span>
      </RouterLink>
      <ThemeToggle />
    </header>
    <main class="auth-main">
      <div class="auth-card"><RouterView /></div>
    </main>
    <footer class="auth-footer">
      <RouterLink to="/">
        <AppIcon name="arrow-left" :size="15" />
        Back to the public site
      </RouterLink>
    </footer>
  </div>
</template>

<style scoped>
.auth-shell {
  min-height: 100vh;
  min-height: 100dvh;
  display: grid;
  grid-template-rows: auto minmax(0, 1fr) auto;
  background:
    radial-gradient(circle at 15% 15%, var(--color-accent-soft), transparent 30rem),
    var(--color-bg);
}

.auth-header {
  min-height: var(--header-height);
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding-inline: clamp(var(--space-4), 4vw, var(--space-8));
}

.auth-brand {
  display: inline-flex;
  align-items: center;
  gap: var(--space-2);
  color: var(--color-text);
  font-weight: 760;
  letter-spacing: 0.04em;
  text-decoration: none;
}

.auth-brand :deep(svg) {
  color: var(--color-accent);
}

.auth-main {
  display: grid;
  place-items: center;
  padding: var(--space-6) var(--space-4);
}

.auth-card {
  width: min(100%, 27rem);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-xl);
  background: var(--color-surface);
  box-shadow: var(--shadow-md);
  padding: clamp(var(--space-6), 5vw, var(--space-8));
}

.auth-footer {
  display: flex;
  justify-content: center;
  padding: var(--space-5);
}

.auth-footer a {
  display: inline-flex;
  align-items: center;
  gap: var(--space-2);
  color: var(--color-text-muted);
  font-size: 0.8125rem;
  text-decoration: none;
}

.auth-footer a:hover {
  color: var(--color-text);
}
</style>
