/** Conversa com o orquestrador. Ele escolhe as ações, roda o Agente BPR um
 * endereço por vez e resume. O turno roda no servidor: fechar a aba não
 * interrompe uma análise, e a conversa volta ao reabrir (enquanto o
 * servidor estiver no ar). */

import {
  Alert,
  Badge,
  Button,
  Chip,
  Collapse,
  Group,
  Loader,
  Paper,
  ScrollArea,
  Stack,
  Text,
  Textarea,
  Title,
} from "@mantine/core";
import { useDisclosure } from "@mantine/hooks";
import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";

import { ErroDaApi } from "../api/cliente";
import { useConversa, useEnviarMensagem, useNovaConversa } from "../api/consultas";
import type { MensagemConversa } from "../api/tipos";
import { RespostaDoModelo } from "../componentes/RespostaDoModelo";
import { Erro } from "../ui/Estado";
import { loteDaResposta } from "./conversas";

const CHAVE_SESSAO = "bpr:sessao";

const SUGESTOES = [
  "Quais ações o Agente BPR executa?",
  "O ambiente está pronto para um lote com extração?",
  "Analise o endereço ACACLD0001 só quanto à franquia.",
];

const NOMES: Record<string, string> = {
  listar_acoes_bpr: "Consultou o catálogo de ações",
  verificar_ambiente_bpr: "Conferiu o ambiente",
  analisar_enderecos: "Analisou endereços",
  consultar_resultado: "Consultou um resultado",
};

function lerSessao(): string | null {
  try {
    return sessionStorage.getItem(CHAVE_SESSAO);
  } catch {
    return null;
  }
}

function gravarSessao(id: string | null) {
  try {
    if (id) sessionStorage.setItem(CHAVE_SESSAO, id);
    else sessionStorage.removeItem(CHAVE_SESSAO);
  } catch {
    // Sem sessionStorage (janela privada restrita): a conversa só não volta ao recarregar.
  }
}

function Ferramenta({ mensagem }: { mensagem: Extract<MensagemConversa, { tipo: "ferramenta" | "resultado" }> }) {
  const [aberto, { toggle }] = useDisclosure(false);
  const conteudo = mensagem.tipo === "ferramenta" ? mensagem.argumentos : mensagem.resposta;
  const lote = mensagem.tipo === "resultado" ? loteDaResposta(mensagem.resposta) : null;
  const status = mensagem.tipo === "resultado" && conteudo && typeof conteudo === "object" && "status" in conteudo
    ? String((conteudo as { status: unknown }).status) : null;
  return (
    <Paper withBorder radius="md" px="sm" py={6} bg="var(--bpr-destaque-suave)" maw="85%">
      <Group gap="xs" wrap="nowrap">
        <i className={`bi ${mensagem.tipo === "ferramenta" ? "bi-gear" : "bi-check2"}`} />
        <Text size="sm">
          {mensagem.tipo === "ferramenta" ? (NOMES[mensagem.nome] ?? mensagem.nome) : "Resposta"}
          {" "}<Text span size="xs" c="dimmed" ff="monospace">{mensagem.nome}</Text>
        </Text>
        {status && <Badge size="xs" variant="light" color={status === "recusado" ? "red" : "teal"}>{status}</Badge>}
        {lote && (
          <Button component={Link} to={`/lotes/${lote}`} size="compact-xs" variant="light">
            Abrir lote
          </Button>
        )}
        <Button size="compact-xs" variant="subtle" ml="auto" onClick={toggle}>
          {aberto ? "Ocultar" : "Detalhes"}
        </Button>
      </Group>
      <Collapse expanded={aberto}>
        <pre className="bpr-json" style={{ maxHeight: 280, overflow: "auto", marginTop: 6 }}>
          {JSON.stringify(conteudo, null, 2)}
        </pre>
      </Collapse>
    </Paper>
  );
}

function Mensagem({ mensagem }: { mensagem: MensagemConversa }) {
  if (mensagem.tipo === "ferramenta" || mensagem.tipo === "resultado") {
    return <Ferramenta mensagem={mensagem} />;
  }
  if (mensagem.papel === "sistema") {
    return <Alert color="red" variant="light">{mensagem.texto}</Alert>;
  }
  const doUsuario = mensagem.papel === "usuario";
  return (
    <Paper radius="lg" px="md" py="sm" maw="85%" withBorder={!doUsuario}
      ml={doUsuario ? "auto" : undefined}
      bg={doUsuario ? "var(--mantine-primary-color-filled)" : "var(--bpr-superficie)"}
      c={doUsuario ? "white" : undefined}>
      {doUsuario ? <Text size="sm" style={{ whiteSpace: "pre-wrap" }}>{mensagem.texto}</Text> : (
        <RespostaDoModelo texto={mensagem.texto} />
      )}
    </Paper>
  );
}

export function Conversa() {
  const [sessaoId, setSessaoId] = useState<string | null>(lerSessao);
  const [texto, setTexto] = useState("");
  const nova = useNovaConversa();
  const conversa = useConversa(sessaoId);
  const enviar = useEnviarMensagem(sessaoId);
  const fim = useRef<HTMLDivElement>(null);

  // Sem sessão, ou a do sessionStorage sumiu (servidor reiniciado): abre
  // outra. Se abrir falhar, não tenta em laço: o erro aparece na tela.
  const perdida = conversa.error instanceof ErroDaApi && conversa.error.status === 404;
  const { mutate: abrir, isPending: abrindo, isError: falhouAoAbrir } = nova;
  useEffect(() => {
    if ((!sessaoId || perdida) && !abrindo && !falhouAoAbrir) {
      abrir(undefined, {
        onSuccess: (c) => {
          gravarSessao(c.sessao_id);
          setSessaoId(c.sessao_id);
        },
      });
    }
  }, [sessaoId, perdida, abrir, abrindo, falhouAoAbrir]);

  const mensagens = conversa.data?.mensagens ?? [];
  const ocupada = Boolean(conversa.data?.ocupada) || enviar.isPending;

  useEffect(() => {
    fim.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [mensagens.length]);

  function mandar(conteudo: string) {
    const limpo = conteudo.trim();
    if (!limpo || ocupada || !sessaoId) return;
    enviar.mutate(limpo, { onSuccess: () => setTexto("") });
  }

  function recomecar() {
    gravarSessao(null);
    setSessaoId(null);
  }

  return (
    <Stack gap="md" className="bpr-pagina" h="calc(100dvh - 110px)">
      <Group justify="space-between">
        <div>
          <Title order={2}>Conversa</Title>
          <Text c="dimmed" size="sm">
            Peça análises em linguagem natural. A extração de TSSR só roda depois de você confirmar.
          </Text>
        </div>
        <Button variant="default" size="xs" onClick={recomecar} leftSection={<i className="bi bi-arrow-repeat" />}>
          Nova conversa
        </Button>
      </Group>

      <Paper withBorder radius="lg" p="md" style={{ flex: 1, minHeight: 0 }}>
        <ScrollArea h="100%" offsetScrollbars>
          <Stack gap="sm">
            {mensagens.length === 0 && (
              <Stack align="center" py="xl" gap="sm">
                <Text c="dimmed">Comece com uma pergunta, por exemplo:</Text>
                <Group gap="xs" justify="center">
                  {SUGESTOES.map((s) => (
                    <Chip key={s} checked={false} onChange={() => mandar(s)} variant="outline">{s}</Chip>
                  ))}
                </Group>
              </Stack>
            )}
            {mensagens.map((m, i) => <Mensagem key={i} mensagem={m} />)}
            {ocupada && (
              <Group gap="xs"><Loader size="xs" type="dots" /><Text size="sm" c="dimmed">O orquestrador está trabalhando…</Text></Group>
            )}
            <div ref={fim} />
          </Stack>
        </ScrollArea>
      </Paper>

      {(nova.isError || enviar.isError) && <Erro erro={nova.error ?? enviar.error} />}

      <Group align="flex-end" gap="sm">
        <Textarea
          aria-label="Mensagem"
          placeholder="Ex.: Analise ACACLD0001 e ACACLD0002 quanto a contrato e franquia."
          autosize
          minRows={1}
          maxRows={6}
          style={{ flex: 1 }}
          value={texto}
          onChange={(e) => setTexto(e.currentTarget.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              mandar(texto);
            }
          }}
        />
        <Button onClick={() => mandar(texto)} disabled={!texto.trim() || ocupada}
          leftSection={<i className="bi bi-send" />}>
          Enviar
        </Button>
      </Group>
    </Stack>
  );
}
