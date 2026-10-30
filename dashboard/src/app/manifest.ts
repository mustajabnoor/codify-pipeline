import type { MetadataRoute } from "next";

// Lets the dashboard be installed to a phone's home screen (CLAUDE.md §8).
export default function manifest(): MetadataRoute.Manifest {
  return {
    name: "Codify Pipeline",
    short_name: "Pipeline",
    description: "Lead pipeline for Codify Labs",
    start_url: "/",
    display: "standalone",
    background_color: "#ffffff",
    theme_color: "#171717",
    icons: [
      { src: "/icon-192.png", sizes: "192x192", type: "image/png" },
      { src: "/icon-512.png", sizes: "512x512", type: "image/png" },
      { src: "/icon-512.png", sizes: "512x512", type: "image/png", purpose: "maskable" },
    ],
  };
}
