import { createMDX } from 'fumadocs-mdx/next';

const withMDX = createMDX();

/** GitHub project site: https://coscatld.github.io/MathTutor/ */
export const REPO_NAME = 'MathTutor';
export const BASE_PATH = `/${REPO_NAME}`;

/** @type {import('next').NextConfig} */
const config = {
  output: 'export',
  reactStrictMode: true,
  basePath: BASE_PATH,
  assetPrefix: BASE_PATH,
  trailingSlash: true,
  images: {
    unoptimized: true,
  },
};

export default withMDX(config);
