import { Node } from '@tiptap/core'

/**
 * Notes v2 (T3.2) — lightweight TipTap nodes for uploaded media.
 *
 * Files are uploaded to the backend (`POST /api/v1/crm/notes/media`) and the
 * returned persistent URL is stored as a node attribute, so the media renders
 * in any session (never a blob: URL).
 */

export const Video = Node.create({
  name: 'video',
  group: 'block',
  atom: true,
  draggable: true,
  addAttributes() {
    return {
      src: { default: null },
      title: { default: null },
    }
  },
  parseHTML() {
    return [{ tag: 'video[src]' }]
  },
  renderHTML({ HTMLAttributes }) {
    return ['video', {
      ...HTMLAttributes,
      controls: 'true',
      preload: 'metadata',
      style: 'max-width:100%;border-radius:8px',
    }]
  },
})

export const Audio = Node.create({
  name: 'audio',
  group: 'block',
  atom: true,
  draggable: true,
  addAttributes() {
    return {
      src: { default: null },
      title: { default: null },
    }
  },
  parseHTML() {
    return [{ tag: 'audio[src]' }]
  },
  renderHTML({ HTMLAttributes }) {
    return ['audio', {
      ...HTMLAttributes,
      controls: 'true',
      preload: 'metadata',
      style: 'width:100%',
    }]
  },
})
