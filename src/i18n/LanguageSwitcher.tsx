import { useTranslation } from 'react-i18next';
import { setLanguage, getLanguage, type Lang } from './config';

export default function LanguageSwitcher() {
  const { t } = useTranslation();
  const current = getLanguage();

  return (
    <select
      value={current}
      onChange={(e) => setLanguage(e.target.value as Lang)}
      className="language-switcher"
      aria-label={t('settings.profile.language')}
    >
      <option value="zh-TW">{t('settings.language.zh-TW')}</option>
      <option value="zh-CN">{t('settings.language.zh-CN')}</option>
      <option value="en">{t('settings.language.en')}</option>
    </select>
  );
}
