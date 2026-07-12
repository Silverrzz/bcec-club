<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { api } from '@/api/client'
import { useConfirm } from '@/composables/useConfirm'
import { useToast } from '@/composables/useToast'
import AdminEmptyState from '@/components/admin/AdminEmptyState.vue'
import AdminPageHeader from '@/components/admin/AdminPageHeader.vue'
import InlineFeedback from '@/components/admin/InlineFeedback.vue'
import StatusBadge from '@/components/admin/StatusBadge.vue'
import { errorText, formatNumber } from '@/components/admin/format'
import type { EngineFamily } from '@/components/admin/types'

interface Response { engines: EngineFamily[]; game_counts: Record<string, number> }
const toast = useToast()
const { confirm } = useConfirm()
const data = ref<Response | null>(null)
const loading = ref(true)
const error = ref('')
const query = ref('')
const activeOnly = ref(false)
const deleting = ref<number | null>(null)
const filtered = computed(() => { const needle=query.value.trim().toLowerCase(); return (data.value?.engines??[]).filter(e=>(!activeOnly.value||e.active)&&(!needle||`${e.name} ${e.author??''} ${e.versions.map(v=>v.version).join(' ')}`.toLowerCase().includes(needle))) })

async function load(){loading.value=true;try{data.value=await api.get<Response>('/api/admin/engines')}catch(cause){error.value=errorText(cause)}finally{loading.value=false}}
async function remove(engine:EngineFamily){if(engine.versions.length){error.value='Delete every version before deleting the engine identity.';return}if(!await confirm({title:'Delete engine?',message:`Delete “${engine.name}”?`,confirmLabel:'Delete engine',tone:'danger'}))return;deleting.value=engine.id;try{const response=await api.delete<{message:string}>(`/api/admin/engines/${engine.id}`);toast.success(response.message);await load()}catch(cause){error.value=errorText(cause);toast.error(cause)}finally{deleting.value=null}}
onMounted(load)
</script>

<template>
  <div class="admin-page page-stack">
    <AdminPageHeader title="Engines"><template #actions><RouterLink class="button button--primary" to="/admin/engines/new">Register engine</RouterLink></template></AdminPageHeader>
    <InlineFeedback :message="error" />
    <section class="panel engine-index">
      <div class="toolbar"><input v-model="query" class="input" type="search" placeholder="Search engine, author, or version"><label><input v-model="activeOnly" type="checkbox"> Active only</label><span>{{ filtered.length }} engines</span></div>
      <div v-if="loading" class="loading">Loading engines…</div>
      <div v-else-if="filtered.length" class="grid">
        <article v-for="engine in filtered" :key="engine.id" class="engine-card">
          <div class="heading"><div class="mark">{{ engine.name[0]?.toUpperCase() }}</div><div><h2>{{ engine.name }}</h2><p>{{ engine.author || 'Unknown author' }}</p></div><StatusBadge :status="engine.active?'active':'inactive'" /></div>
          <div class="versions"><div v-for="version in engine.versions" :key="version.id" class="version"><div><strong>{{ version.version }}</strong><small>{{ version.binary_filename }}</small></div><div><span>{{ formatNumber(data?.game_counts[String(version.id)]) }} games</span><StatusBadge :status="version.storage_status==='ready'?(version.active?'active':'inactive'):version.storage_status||'missing'" /></div></div><p v-if="!engine.versions.length">No versions uploaded</p></div>
          <div class="actions"><RouterLink class="button button--secondary button--small" :to="`/admin/engines/${engine.id}/edit`">Manage & upload</RouterLink><button class="button button--danger button--small" type="button" :disabled="deleting===engine.id||engine.versions.length>0" @click="remove(engine)">Delete</button></div>
        </article>
      </div>
      <AdminEmptyState v-else :title="query||activeOnly?'No matching engines':'No engines registered'"><RouterLink v-if="!query&&!activeOnly" class="button button--primary button--small" to="/admin/engines/new">Register engine</RouterLink></AdminEmptyState>
    </section>
  </div>
</template>

<style scoped>
.engine-index{overflow:hidden;padding:0}.toolbar{align-items:center;border-bottom:1px solid var(--color-border);display:flex;gap:.75rem;padding:.75rem}.toolbar .input{flex:1;max-width:28rem}.toolbar label,.toolbar span{color:var(--color-text-muted);font-size:.72rem}.grid{display:grid;gap:.8rem;grid-template-columns:repeat(auto-fill,minmax(min(100%,21rem),1fr));padding:.8rem}.engine-card{border:1px solid var(--color-border);border-radius:var(--radius-md);display:grid;gap:.8rem;padding:.9rem}.heading{align-items:center;display:grid;gap:.65rem;grid-template-columns:auto minmax(0,1fr) auto}.mark{align-items:center;background:color-mix(in srgb,var(--color-accent) 10%,transparent);border-radius:.5rem;color:var(--color-accent);display:flex;font-weight:750;height:2.1rem;justify-content:center;width:2.1rem}.heading h2{font-size:.88rem;margin:0}.heading p{color:var(--color-text-muted);font-size:.68rem;margin:.15rem 0 0}.versions{border-block:1px solid var(--color-border);display:grid}.version{align-items:center;border-bottom:1px solid var(--color-border);display:flex;justify-content:space-between;padding:.55rem 0}.version:last-child{border:0}.version>div{display:grid;gap:.15rem}.version>div:last-child{align-items:end}.version strong{font-size:.76rem}.version small,.version span,.versions>p{color:var(--color-text-muted);font-size:.66rem}.versions>p{margin:.7rem 0}.actions{display:flex;gap:.5rem;margin-top:auto}.loading{color:var(--color-text-muted);min-height:14rem;padding:2rem}@media(max-width:38rem){.toolbar{align-items:stretch;flex-wrap:wrap}.toolbar .input{flex-basis:100%;max-width:none}}
</style>
