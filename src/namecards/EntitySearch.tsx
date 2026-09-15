// ═══════════════════════════════════════════════════════════
// EntitySearch — bridge re-export
// The V2 NameCard module expects `import { EntitySearch } from './EntitySearch'`
// (named export). The underlying implementation lives in the shared module.
// ═══════════════════════════════════════════════════════════
import EntitySearch from '../modules/shared/EntitySearch'
export { EntitySearch }
export default EntitySearch
