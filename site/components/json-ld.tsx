import { SITE_NAME, SITE_URL, REPO_URL } from '@/lib/site';

export function JsonLd() {
  const data = {
    '@context': 'https://schema.org',
    '@type': 'SoftwareApplication',
    name: SITE_NAME,
    applicationCategory: 'EducationalApplication',
    operatingSystem: 'Windows, macOS',
    license: 'https://www.apache.org/licenses/LICENSE-2.0',
    url: SITE_URL,
    codeRepository: REPO_URL,
    description:
      'Open-source math tutoring system with verifiable solving, graded guidance, and learning-process evidence.',
  };
  return (
    <script type="application/ld+json" dangerouslySetInnerHTML={{ __html: JSON.stringify(data) }} />
  );
}
