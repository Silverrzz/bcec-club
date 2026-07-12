<script setup lang="ts">
import { computed, ref, watch } from "vue";
import { RouterLink, RouterView, useRoute } from "vue-router";

import AppIcon from "@/components/ui/AppIcon.vue";
import BaseButton from "@/components/ui/BaseButton.vue";
import ThemeToggle from "@/components/ui/ThemeToggle.vue";

const route = useRoute();
const menuOpen = ref(false);
const compactGameLayout = computed(() => route.name === "tournament");

const navItems = [
  { label: "Live", to: "/" },
  { label: "Tournaments", to: "/tournaments" },
  { label: "Ratings", to: "/ratings" },
  { label: "Archive", to: "/archive" },
] as const;

function navActive(path: string): boolean {
  return path === "/" ? route.path === path : route.path === path || route.path.startsWith(`${path}/`);
}

watch(
  () => route.fullPath,
  () => (menuOpen.value = false),
);
</script>

<template>
  <div class="public-shell" :class="{ 'public-shell--game': compactGameLayout }">
    <a class="skip-link" href="#main-content">Skip to content</a>
    <header class="public-header" :class="{ 'public-header--compact': compactGameLayout }">
      <div class="page-container public-header__inner">
        <RouterLink class="brand" to="/" aria-label="COPE Chess home">
          <span class="brand__mark"><AppIcon name="logo" :size="25" /></span>
          <span class="brand__text">COPE</span>
        </RouterLink>

        <nav id="public-navigation" class="public-nav" :class="{ 'public-nav--open': menuOpen }" aria-label="Primary navigation">
          <RouterLink
            v-for="item in navItems"
            :key="item.to"
            class="public-nav__link"
            :class="{ 'public-nav__link--active': navActive(item.to) }"
            :to="item.to"
            active-class=""
            exact-active-class=""
          >
            {{ item.label }}
          </RouterLink>
          <RouterLink class="public-nav__link public-nav__admin-mobile" to="/admin">Admin</RouterLink>
        </nav>

        <div class="public-header__actions">
          <ThemeToggle />
          <BaseButton class="public-header__admin" variant="ghost" size="small" to="/admin">
            Admin
          </BaseButton>
          <BaseButton
            class="public-header__menu"
            variant="ghost"
            size="small"
            icon-only
            :aria-expanded="menuOpen"
            aria-controls="public-navigation"
            :aria-label="menuOpen ? 'Close navigation' : 'Open navigation'"
            @click="menuOpen = !menuOpen"
          >
            <template #icon><AppIcon :name="menuOpen ? 'close' : 'menu'" :size="20" /></template>
            {{ menuOpen ? "Close navigation" : "Open navigation" }}
          </BaseButton>
        </div>
      </div>
    </header>

    <main id="main-content" class="public-main" :class="{ 'public-main--game': compactGameLayout }" tabindex="-1">
      <RouterView />
    </main>

    <footer class="public-footer">
      <div class="page-container public-footer__inner">
        <span>COPE Chess</span>
        <span class="public-footer__note">Open tournament management and live results.</span>
      </div>
    </footer>
  </div>
</template>

<style scoped>
.public-shell {
  min-height: 100vh;
  min-height: 100dvh;
  display: flex;
  flex-direction: column;
}

.public-header {
  position: sticky;
  z-index: 50;
  top: 0;
  border-bottom: 1px solid var(--color-border);
  background: var(--color-header);
  backdrop-filter: blur(14px);
}

.public-header__inner {
  min-height: var(--header-height);
  display: grid;
  grid-template-columns: auto minmax(0, 1fr) auto;
  align-items: center;
  gap: var(--space-6);
}

.public-header--compact .public-header__inner {
  min-height: 2.85rem;
}

.public-header--compact .public-nav__link {
  padding-block: 0.38rem;
}

.brand {
  display: inline-flex;
  align-items: center;
  gap: var(--space-2);
  color: var(--color-text);
  font-weight: 760;
  letter-spacing: 0.04em;
  text-decoration: none;
}

.brand__mark {
  color: var(--color-accent);
}

.public-nav {
  display: flex;
  align-items: center;
  gap: var(--space-1);
}

.public-nav__link {
  border-radius: var(--radius-md);
  color: var(--color-text-muted);
  padding: 0.5rem 0.7rem;
  font-size: 0.875rem;
  font-weight: 620;
  text-decoration: none;
  transition:
    background-color var(--transition-fast),
    color var(--transition-fast);
}

.public-nav__link:hover {
  background: var(--color-surface-hover);
  color: var(--color-text);
}

.public-nav__link--active {
  background: var(--color-accent-soft);
  color: var(--color-accent);
}

.public-header__actions {
  display: flex;
  align-items: center;
  gap: var(--space-1);
}

.public-header__menu {
  display: none;
}

.public-nav__admin-mobile {
  display: none;
}

.public-main {
  min-width: 0;
  flex: 1 0 auto;
  padding-block: clamp(var(--space-6), 4vw, var(--space-12));
}

.public-main:focus {
  outline: none;
}

.public-main--game {
  padding-block: 0;
}

.public-shell--game .public-footer {
  display: none;
}

.public-footer {
  border-top: 1px solid var(--color-border);
  background: var(--color-bg-subtle);
}

.public-footer__inner {
  min-height: 4.5rem;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-4);
  color: var(--color-text-muted);
  font-size: 0.8125rem;
}

@media (max-width: 42rem) {
  .public-header__inner {
    gap: var(--space-3);
  }

  .public-nav {
    position: absolute;
    top: calc(100% + 1px);
    right: var(--space-4);
    left: var(--space-4);
    display: none;
    align-items: stretch;
    flex-direction: column;
    gap: var(--space-1);
    border: 1px solid var(--color-border-strong);
    border-radius: var(--radius-lg);
    background: var(--color-surface-raised);
    box-shadow: var(--shadow-md);
    padding: var(--space-2);
  }

  .public-nav--open {
    display: flex;
  }

  .public-nav__link {
    padding: 0.7rem var(--space-3);
  }

  .public-nav__admin-mobile {
    display: block;
    border-top: 1px solid var(--color-border);
    border-radius: 0 0 var(--radius-md) var(--radius-md);
    margin-top: var(--space-1);
  }

  .public-header__menu {
    display: inline-flex;
  }

  .public-header__admin {
    display: none;
  }

  .public-footer__inner {
    align-items: flex-start;
    flex-direction: column;
    justify-content: center;
    gap: var(--space-1);
    padding-block: var(--space-4);
  }
}
</style>
