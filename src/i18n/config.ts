import i18n from 'i18next';
import { initReactI18next } from 'react-i18next';
import en from './locales/en.json';
import zhTW from './locales/zh-TW.json';

export type Lang = 'en' | 'zh-TW' | 'zh-CN';

// Local bundles = boot-time fallback (works offline / before API resolves);
// DB-backed overrides are fetched at runtime so admin edits apply instantly.
const localBundles: Record<string, object> = {
  en,
  'zh-TW': zhTW,
  'zh-CN': zhTW, // interim: replaced by /api/v1/i18n/resources?locale=zh-CN once loaded
};

i18n.use(initReactI18next).init({
  resources: Object.fromEntries(
    Object.entries(localBundles).map(([lng, bundle]) => [lng, { translation: bundle }]),
  ),
  lng: localStorage.getItem('i18n_lang') || 'zh-TW',
  fallbackLng: 'en',
  interpolation: { escapeValue: false },
});

async function loadRemote(lang: Lang) {
  try {
    const res = await fetch(`/api/v1/i18n/resources?locale=${encodeURIComponent(lang)}`, {
      headers: { Accept: 'application/json' },
    });
    if (!res.ok) return;
    const data = await res.json();
    if (data && typeof data === 'object') {
      i18n.addResourceBundle(lang, 'translation', data, true, true);
      if (i18n.language === lang) i18n.emit('languageChanged', lang); // re-render
    }
  } catch {
    /* offline — local bundle stays */
  }
}

/** Load DB-backed translations for a language (keeps local fallback until it resolves) */
export function primeLanguage(lang: Lang) {
  loadRemote(lang);
}

export default i18n;

/** Toggle language and persist preference */
export function setLanguage(lang: Lang) {
  localStorage.setItem('i18n_lang', lang);
  i18n.changeLanguage(lang);
  loadRemote(lang); // refresh DB-backed copy on every switch
}

/** Get current language */
export function getLanguage(): Lang {
  return (i18n.language as Lang) || 'zh-TW';
}

// Prime the initial language with DB-backed strings (no-op if fetch fails)
primeLanguage(getLanguage());
