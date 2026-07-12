<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from "vue";
import { RouterLink, RouterView, useRoute, useRouter } from "vue-router";

import { api } from "@/api/client";
import AppIcon from "@/components/ui/AppIcon.vue";
import BaseButton from "@/components/ui/BaseButton.vue";
import ThemeToggle from "@/components/ui/ThemeToggle.vue";
import { useToast } from "@/composables/useToast";
import { useSessionStore } from "@/stores/session";
import type { IconName } from "@/types/icons";

const route = useRoute();
const router = useRouter();
const session = useSessionStore();
const toast = useToast();
const sidebarOpen = ref(false);
const signingOut = ref(false);
const mobileQuery = window.matchMedia("(max-width: 52rem)");
const mobileViewport = ref(mobileQuery.matches);
const sidebarUnavailable = computed(() => mobileViewport.value && !sidebarOpen.value);

function syncMobileViewport(event: MediaQueryListEvent): void {
  mobileViewport.value = event.matches;
}

onMounted(() => mobileQuery.addEventListener("change", syncMobileViewport));
onBeforeUnmount(() => mobileQuery.removeEventListener("change", syncMobileViewport));

const navGroups: { label: string; items: { label: string; to: string; icon: IconName }[] }[] = [
  { label: "Overview", items: [{ label: "Dashboard", to: "/admin", icon: "home" }] },
  {
    label: "Competition",
    items: [
      { label: "Tournaments", to: "/admin/tournaments", icon: "trophy" },
      { label: "Categories", to: "/admin/categories", icon: "tag" },
    ],
  },
  {
    label: "Assets",
    items: [
      { label: "Engines", to: "/admin/engines", icon: "engine" },
      { label: "Opening suites", to: "/admin/openings", icon: "book-open" },
    ],
  },
  {
    label: "Operations",
    items: [
      { label: "Workers", to: "/admin/workers", icon: "server" },
      { label: "Chat", to: "/admin/chat", icon: "message-square" },
    ],
  },
];

function navActive(path: string): boolean {
  return path === "/admin" ? route.path === path : route.path === path || route.path.startsWith(`${path}/`);
}

watch(
  () => route.fullPath,
  () => (sidebarOpen.value = false),
);

async function signOut(): Promise<void> {
  signingOut.value = true;
  try {
    await api.delete<void>("/api/session");
    session.clear();
    await router.replace({ name: "admin-login" });
  } catch (error) {
    toast.error(error);
  } finally {
    signingOut.value = false;
  }
}
</script>

<template>
  <div class="admin-shell">
    <a class="skip-link" href="#admin-content">Skip to content</a>

    <header class="admin-topbar">
      <div class="admin-topbar__left">
        <BaseButton
          class="admin-topbar__menu"
          variant="ghost"
          size="small"
          icon-only
          :aria-expanded="sidebarOpen"
          aria-controls="admin-sidebar"
          :aria-label="sidebarOpen ? 'Close navigation' : 'Open navigation'"
          @click="sidebarOpen = !sidebarOpen"
        >
          <template #icon><AppIcon :name="sidebarOpen ? 'close' : 'menu'" :size="20" /></template>
          {{ sidebarOpen ? "Close navigation" : "Open navigation" }}
        </BaseButton>
        <RouterLink class="admin-brand" to="/admin" aria-label="COPE administration home">
          <span class="admin-brand__mark"><AppIcon name="logo" :size="24" /></span>
          <span>COPE <span class="admin-brand__qualifier">Admin</span></span>
        </RouterLink>
      </div>
      <div class="admin-topbar__actions">
        <ThemeToggle />
        <BaseButton variant="ghost" size="small" to="/">
          <template #icon><AppIcon name="external-link" :size="16" /></template>
          <span class="admin-topbar__action-label">View site</span>
        </BaseButton>
        <BaseButton variant="ghost" size="small" :loading="signingOut" @click="signOut">
          <template #icon><AppIcon name="log-out" :size="16" /></template>
          <span class="admin-topbar__action-label">Sign out</span>
        </BaseButton>
      </div>
    </header>

    <aside
      id="admin-sidebar"
      class="admin-sidebar"
      :class="{ 'admin-sidebar--open': sidebarOpen }"
      :aria-hidden="sidebarUnavailable ? 'true' : undefined"
      :inert="sidebarUnavailable"
    >
      <nav class="admin-nav" aria-label="Administration">
        <section v-for="group in navGroups" :key="group.label" class="admin-nav__group">
          <h2 class="admin-nav__label">{{ group.label }}</h2>
          <RouterLink
            v-for="item in group.items"
            :key="item.to"
            class="admin-nav__link"
            :class="{ 'admin-nav__link--active': navActive(item.to) }"
            :to="item.to"
            active-class=""
            exact-active-class=""
          >
            <AppIcon :name="item.icon" :size="18" />
            <span>{{ item.label }}</span>
          </RouterLink>
        </section>
      </nav>
    </aside>

    <button
      v-if="sidebarOpen"
      class="admin-sidebar-backdrop"
      type="button"
      aria-label="Close navigation"
      @click="sidebarOpen = false"
    />

    <main id="admin-content" class="admin-content" tabindex="-1">
      <div class="admin-content__inner"><RouterView /></div>
    </main>
  </div>
</template>

<style scoped>
.admin-shell {
  min-height: 100vh;
  min-height: 100dvh;
  display: grid;
  grid-template-columns: var(--sidebar-width) minmax(0, 1fr);
  grid-template-rows: var(--header-height) minmax(0, 1fr);
  background: var(--color-bg);
}

.admin-topbar {
  position: sticky;
  z-index: 60;
  top: 0;
  grid-column: 1 / -1;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-4);
  border-bottom: 1px solid var(--color-border);
  background: var(--color-header);
  padding: 0 clamp(var(--space-3), 2vw, var(--space-6));
  backdrop-filter: blur(14px);
}

.admin-topbar__left,
.admin-topbar__actions {
  display: flex;
  align-items: center;
  gap: var(--space-1);
}

.admin-brand {
  display: inline-flex;
  align-items: center;
  gap: var(--space-2);
  color: var(--color-text);
  font-weight: 740;
  letter-spacing: 0.02em;
  text-decoration: none;
}

.admin-brand__mark {
  color: var(--color-accent);
}

.admin-brand__qualifier {
  color: var(--color-text-muted);
  font-weight: 560;
}

.admin-topbar__menu {
  display: none;
}

.admin-sidebar {
  position: sticky;
  top: var(--header-height);
  height: calc(100vh - var(--header-height));
  height: calc(100dvh - var(--header-height));
  display: flex;
  flex-direction: column;
  border-right: 1px solid var(--color-border);
  background: var(--color-bg-subtle);
  padding: var(--space-4) var(--space-3);
}

.admin-nav {
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
}

.admin-nav__group {
  display: flex;
  flex-direction: column;
  gap: var(--space-1);
}

.admin-nav__label {
  padding: 0 var(--space-3) var(--space-1);
  color: var(--color-text-faint);
  font-size: 0.625rem;
  font-weight: 720;
  letter-spacing: 0.1em;
  text-transform: uppercase;
}

.admin-nav__link {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  border-radius: var(--radius-md);
  color: var(--color-text-muted);
  padding: 0.62rem var(--space-3);
  font-size: 0.875rem;
  font-weight: 610;
  text-decoration: none;
  transition:
    background-color var(--transition-fast),
    color var(--transition-fast);
}

.admin-nav__link:hover {
  background: var(--color-surface-hover);
  color: var(--color-text);
}

.admin-nav__link--active {
  background: var(--color-accent-soft);
  color: var(--color-accent);
}

.admin-content {
  min-width: 0;
  overflow: clip;
}

.admin-content:focus {
  outline: none;
}

.admin-content__inner {
  width: min(100%, var(--content-max));
  min-height: 100%;
  margin-inline: auto;
  padding: clamp(var(--space-5), 3vw, var(--space-10));
}

.admin-sidebar-backdrop {
  display: none;
}

@media (max-width: 52rem) {
  .admin-shell {
    grid-template-columns: 1fr;
  }

  .admin-topbar__menu {
    display: inline-flex;
  }

  .admin-sidebar {
    position: fixed;
    z-index: 55;
    top: var(--header-height);
    bottom: 0;
    left: 0;
    width: min(var(--sidebar-width), calc(100vw - 3rem));
    height: auto;
    box-shadow: var(--shadow-md);
    transform: translateX(-105%);
    transition: transform var(--transition-base);
  }

  .admin-sidebar--open {
    transform: none;
  }

  .admin-sidebar-backdrop {
    position: fixed;
    z-index: 50;
    inset: var(--header-height) 0 0;
    display: block;
    background: var(--color-overlay);
    cursor: default;
  }
}

@media (max-width: 36rem) {
  .admin-topbar__action-label,
  .admin-brand__qualifier {
    display: none;
  }

  .admin-content__inner {
    padding: var(--space-5) var(--space-4) var(--space-8);
  }
}
</style>
