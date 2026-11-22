const nextConfig = {
  experimental: { cpus: 2 },
  webpack(config) {
    // Avoid intermittent Windows WASM hashing/cache failures in this local copy.
    config.cache = false;
    config.output.hashFunction = 'sha256';
    return config;
  },
};
export default nextConfig;
