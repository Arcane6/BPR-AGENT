/** A casca da tela: menu lateral, cabeçalho com a saúde da API e as rotas. */

import {
  ActionIcon,
  AppShell,
  Badge,
  Burger,
  Group,
  NavLink,
  Text,
  Tooltip,
  useMantineColorScheme,
} from "@mantine/core";
import { useDisclosure } from "@mantine/hooks";
import { lazy, Suspense } from "react";
import { Link, Route, Routes, useLocation } from "react-router-dom";

import { useSaude } from "../api/consultas";
import { Carregando, Vazio } from "../ui/Estado";

// Uma página por pedaço do build: a conversa traz o react-markdown, e quem
// só monta lotes não precisa dele.
const NovoLote = lazy(() => import("../paginas/NovoLote").then((m) => ({ default: m.NovoLote })));
const Lotes = lazy(() => import("../paginas/Lotes").then((m) => ({ default: m.Lotes })));
const Lote = lazy(() => import("../paginas/Lote").then((m) => ({ default: m.Lote })));
const Resultados = lazy(() => import("../paginas/Resultados").then((m) => ({ default: m.Resultados })));
const Conversa = lazy(() => import("../paginas/Conversa").then((m) => ({ default: m.Conversa })));

const MENU = [
  { para: "/", rotulo: "Novo lote", icone: "bi-plus-circle", exato: true },
  { para: "/lotes", rotulo: "Lotes", icone: "bi-collection" },
  { para: "/resultados", rotulo: "Resultados", icone: "bi-table" },
  { para: "/conversa", rotulo: "Conversa", icone: "bi-chat-dots" },
];

function Saude() {
  const saude = useSaude();
  if (saude.isError) {
    return <Badge color="red" variant="light">API fora do ar</Badge>;
  }
  if (!saude.data) return null;
  const { lote_em_andamento: lote, lote_fora_da_tela: fora } = saude.data;
  return (
    <Group gap="xs">
      {lote && (
        <Badge component={Link} to={`/lotes/${lote}`} color="tim" variant="filled"
          style={{ cursor: "pointer" }} leftSection={<i className="bi bi-activity" />}>
          Lote em andamento
        </Badge>
      )}
      {fora && <Badge color="orange" variant="light">Lote em andamento pelo chat</Badge>}
      <Tooltip label={`Agente BPR: ${saude.data.modelo_agente} · Orquestrador: ${saude.data.modelo_orquestrador}`}>
        <Badge variant="outline" color="gray" visibleFrom="sm">{saude.data.modelo_agente}</Badge>
      </Tooltip>
    </Group>
  );
}

function TrocarTema() {
  const { colorScheme, setColorScheme } = useMantineColorScheme();
  const escuro = colorScheme === "dark";
  return (
    <ActionIcon variant="default" aria-label="Trocar tema" onClick={() => setColorScheme(escuro ? "light" : "dark")}>
      <i className={`bi ${escuro ? "bi-sun" : "bi-moon-stars"}`} />
    </ActionIcon>
  );
}

export function App() {
  const [aberto, { toggle, close }] = useDisclosure();
  const { pathname } = useLocation();

  return (
    <AppShell
      header={{ height: 56 }}
      navbar={{ width: 220, breakpoint: "sm", collapsed: { mobile: !aberto } }}
      padding="md"
    >
      <AppShell.Header>
        <Group h="100%" px="md" justify="space-between" wrap="nowrap">
          <Group gap="sm" wrap="nowrap">
            <Burger opened={aberto} onClick={toggle} hiddenFrom="sm" size="sm" />
            <i className="bi bi-broadcast-pin" style={{ fontSize: 22, color: "var(--bpr-destaque)" }} />
            <Text fw={700} size="lg" style={{ whiteSpace: "nowrap" }}>Agente BPR</Text>
          </Group>
          <Group gap="sm" wrap="nowrap">
            <Saude />
            <TrocarTema />
          </Group>
        </Group>
      </AppShell.Header>

      <AppShell.Navbar p="sm">
        {MENU.map((item) => (
          <NavLink
            key={item.para}
            component={Link}
            to={item.para}
            label={item.rotulo}
            leftSection={<i className={`bi ${item.icone}`} />}
            active={item.exato ? pathname === item.para : pathname.startsWith(item.para)}
            onClick={close}
          />
        ))}
      </AppShell.Navbar>

      <AppShell.Main>
        <Suspense fallback={<Carregando />}>
        <Routes>
          <Route path="/" element={<NovoLote />} />
          <Route path="/lotes" element={<Lotes />} />
          <Route path="/lotes/:loteId" element={<Lote />} />
          <Route path="/resultados" element={<Resultados />} />
          <Route path="/conversa" element={<Conversa />} />
          <Route path="*" element={<Vazio titulo="Página não encontrada." />} />
        </Routes>
        </Suspense>
      </AppShell.Main>
    </AppShell>
  );
}
