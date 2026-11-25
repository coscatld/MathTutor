export const RELEASE_TAG = 'desktop-20261125';
export const RELEASE_URL = `https://github.com/coscatld/MathTutor/releases/tag/${RELEASE_TAG}`;

export type PlatformId = 'windows-x64' | 'macos-arm64';

export type ReleaseAsset = {
  id: PlatformId;
  filename: string;
  url: string;
  os: string;
  arch: string;
  notes: string;
  notesEn: string;
};

export const CURRENT_ASSETS: ReleaseAsset[] = [
  {
    id: 'windows-x64',
    filename: 'MathTutor-windows-x64.exe',
    url: `https://github.com/coscatld/MathTutor/releases/download/${RELEASE_TAG}/MathTutor-windows-x64.exe`,
    os: 'Windows 10/11',
    arch: 'x64',
    notes: '打开安装程序，按向导完成安装。',
    notesEn:
      'Open the installer and follow the setup wizard.',
  },
  {
    id: 'macos-arm64',
    filename: 'MathTutor-mac-arm64.dmg',
    url: `https://github.com/coscatld/MathTutor/releases/download/${RELEASE_TAG}/MathTutor-mac-arm64.dmg`,
    os: 'macOS',
    arch: 'Apple Silicon',
    notes:
      '打开磁盘映像，将 MathTutor 拖入“应用程序”。',
    notesEn:
      'Open the disk image and drag MathTutor into Applications.',
  },
];
