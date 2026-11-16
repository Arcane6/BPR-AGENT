import { createTheme, type MantineColorsTuple } from "@mantine/core";

/** O tema do portal (coverage-hub/frontend/src/shared/ui/tema.ts): azul TIM
 * no tom 7, Inter, os mesmos raios. A tela do Agente BPR é outro projeto,
 * mas é da mesma área e deve parecer da mesma casa. */
const azulTim: MantineColorsTuple = [
  "#eef2fb", "#d9e1f5", "#b3c3eb", "#8aa3e0", "#5c7fd2",
  "#3360c4", "#1747b3", "#003399", "#002a80", "#001f66",
];

const escuro: MantineColorsTuple = [
  "#dbe4f0", "#b5c1d3", "#8fa0b8", "#64748b", "#3a4558",
  "#2a3446", "#1c2536", "#131a26", "#0b0f17", "#06090f",
];

export const tema = createTheme({
  primaryColor: "tim",
  primaryShade: { light: 7, dark: 6 },
  colors: { tim: azulTim, dark: escuro },
  fontFamily: '"Inter Variable", system-ui, -apple-system, "Segoe UI", Roboto, sans-serif',
  headings: { fontFamily: '"Inter Variable", system-ui, sans-serif', fontWeight: "700" },
  defaultRadius: "md",
  radius: { xs: "4px", sm: "6px", md: "10px", lg: "14px", xl: "20px" },
  cursorType: "pointer",
});
