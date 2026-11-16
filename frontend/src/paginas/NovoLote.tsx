/** Montar e começar um lote: endereços (colados ou de arquivo), ações,
 * extração de TSSR (com confirmação), prévia do escopo e ambiente. */

import {
  Alert,
  Badge,
  Button,
  FileButton,
  Group,
  List,
  Modal,
  NumberInput,
  Paper,
  Stack,
  Switch,
  Text,
  Textarea,
  Title,
} from "@mantine/core";
import { useDebouncedValue } from "@mantine/hooks";
import { useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";

import {
  useAmbiente,
  useEscopo,
  useIniciarLote,
  useLerArquivoEnderecos,
  useSaude,
} from "../api/consultas";
import { SeletorAcoes } from "../componentes/SeletorAcoes";
import { Erro } from "../ui/Estado";
import { contarEnderecos } from "../ui/formatar";

export function NovoLote() {
  const navegar = useNavigate();
  const [texto, setTexto] = useState("");
  const [acoes, setAcoes] = useState<string[]>([]);
  const [permitirExtracao, setPermitirExtracao] = useState(false);
  const [confirmandoExtracao, setConfirmandoExtracao] = useState(false);
  // 4 por padrão: o tempo de um endereço é quase todo espera pelo modelo, e
  // a API repete sozinha quando o Vertex responde 429 (cota).
  const [concorrencia, setConcorrencia] = useState<number>(4);
  const [pularGravados, setPularGravados] = useState(true);

  const { unicos, repetidos } = useMemo(() => contarEnderecos(texto), [texto]);
  const [acoesAdiadas] = useDebouncedValue(acoes, 300);
  const escopo = useEscopo(acoesAdiadas, permitirExtracao);
  const ambiente = useAmbiente(permitirExtracao);
  const saude = useSaude();
  const lerArquivo = useLerArquivoEnderecos();
  const iniciar = useIniciarLote();

  // Vários lotes rodam juntos; só o teto do servidor impede um novo.
  const rodando = (saude.data?.lotes_em_andamento.length ?? 0) + (saude.data?.lotes_fora_da_tela ?? 0);
  const ocupado = Boolean(saude.data && rodando >= saude.data.max_lotes_simultaneos);
  const podeIniciar = unicos.length > 0 && !escopo.isError && ambiente.data?.pode_iniciar === true
    && !ocupado && !iniciar.isPending;

  function aoEscolherArquivo(arquivo: File | null) {
    if (!arquivo) return;
    lerArquivo.mutate(arquivo, {
      onSuccess: (lido) => setTexto((atual) =>
        [atual.trim(), ...lido.enderecos].filter(Boolean).join("\n")),
    });
  }

  function alternarExtracao(ligar: boolean) {
    if (ligar) setConfirmandoExtracao(true);
    else {
      setPermitirExtracao(false);
      setAcoes((atual) => atual.filter((r) => r !== "5.2B"));
    }
  }

  function comecar() {
    iniciar.mutate(
      {
        enderecos: unicos,
        acoes,
        permitir_extracao: permitirExtracao,
        concorrencia: permitirExtracao ? 1 : concorrencia,
        pular_gravados: pularGravados,
      },
      { onSuccess: ({ lote_id }) => navegar(`/lotes/${lote_id}`) },
    );
  }

  return (
    <Stack gap="lg" className="bpr-pagina">
      <div>
        <Title order={2}>Novo lote</Title>
        <Text c="dimmed">
          Um endereço por vez, cada um numa sessão nova do Agente BPR. O resultado de cada
          endereço é gravado assim que ele termina.
        </Text>
      </div>

      {ocupado && (
        <Alert color="orange" icon={<i className="bi bi-hourglass-split" />}
          title={`Já há ${rodando} lotes rodando, o máximo ao mesmo tempo`}>
          Espere um terminar para começar outro.
        </Alert>
      )}
      {!ocupado && rodando > 0 && (
        <Alert color="blue" variant="light" icon={<i className="bi bi-info-circle" />}>
          {rodando === 1 ? "Há 1 lote rodando." : `Há ${rodando} lotes rodando.`} Este começa
          junto com eles; um endereço que já esteja em análise em outro lote fica de lado.
        </Alert>
      )}

      <Paper withBorder p="md" radius="lg">
        <Group justify="space-between" mb="xs">
          <Title order={4}>1. Endereços</Title>
          <FileButton onChange={aoEscolherArquivo} accept=".txt,.csv">
            {(props) => (
              <Button {...props} variant="default" size="xs" loading={lerArquivo.isPending}
                leftSection={<i className="bi bi-upload" />}>
                Carregar TXT ou CSV
              </Button>
            )}
          </FileButton>
        </Group>
        <Textarea
          aria-label="Endereços"
          placeholder={"ACACLD0001\nACACLD0002\n(um por linha, ou separados por vírgula; pode colar uma coluna do Excel)"}
          autosize
          minRows={5}
          maxRows={14}
          value={texto}
          onChange={(e) => setTexto(e.currentTarget.value)}
          styles={{ input: { fontFamily: "monospace" } }}
        />
        <Group gap="xs" mt="xs">
          <Badge variant="light" size="lg" className="bpr-numero">{unicos.length} endereço(s)</Badge>
          {repetidos > 0 && <Badge variant="light" color="gray">{repetidos} repetido(s) ignorado(s)</Badge>}
          {lerArquivo.isError && <Text size="sm" c="red">{lerArquivo.error.message}</Text>}
        </Group>
      </Paper>

      <Paper withBorder p="md" radius="lg">
        <Title order={4} mb="xs">2. Ações</Title>
        <SeletorAcoes marcadas={acoes} aoMudar={setAcoes} permitirExtracao={permitirExtracao} />
      </Paper>

      <Paper withBorder p="md" radius="lg">
        <Title order={4} mb="sm">3. Opções</Title>
        <Stack gap="sm">
          <Switch
            checked={permitirExtracao}
            onChange={(e) => alternarExtracao(e.currentTarget.checked)}
            color="orange"
            label="Autorizar extração de TSSR (Ação 5.2B)"
            description="Processa arquivos da pasta de Input, carrega no BigQuery e move os arquivos."
          />
          <Switch
            checked={pularGravados}
            onChange={(e) => setPularGravados(e.currentTarget.checked)}
            label="Pular endereços já gravados em lotes anteriores"
            description="Para retomar um lote interrompido sem gravar a mesma linha duas vezes no Excel."
          />
          <NumberInput
            label="Endereços em paralelo"
            description={permitirExtracao ? "Com extração, sempre 1." : "Até 8. Se aparecer erro de cota (429) na auditoria, diminua."}
            min={1}
            max={8}
            w={220}
            value={permitirExtracao ? 1 : concorrencia}
            disabled={permitirExtracao}
            onChange={(v) => setConcorrencia(Number(v) || 1)}
          />
        </Stack>
      </Paper>

      <Paper withBorder p="md" radius="lg">
        <Title order={4} mb="xs">4. Conferência</Title>
        <Stack gap="sm">
          {escopo.isError ? <Erro erro={escopo.error} /> : escopo.data && (
            <div>
              <Text size="sm" mb={4}>
                Vai rodar <b>{escopo.data.executar.length}</b> ação(ões):
              </Text>
              <Group gap={4}>
                {escopo.data.executar.map((abrev) => <Badge key={abrev} variant="outline">{abrev}</Badge>)}
              </Group>
              {escopo.data.avisos.length > 0 && (
                <List size="sm" mt="xs" c="dimmed">
                  {escopo.data.avisos.map((a) => <List.Item key={a}>{a}</List.Item>)}
                </List>
              )}
            </div>
          )}
          {ambiente.data && ambiente.data.impedimentos.length > 0 && (
            <Alert color="red" title="O ambiente não está pronto" icon={<i className="bi bi-x-octagon" />}>
              <List size="sm">
                {ambiente.data.impedimentos.map((i) => <List.Item key={i}>{i}</List.Item>)}
              </List>
            </Alert>
          )}
          {ambiente.data && ambiente.data.avisos.length > 0 && (
            <Alert color="orange" variant="light" title="Avisos do ambiente">
              <List size="sm">{ambiente.data.avisos.map((a) => <List.Item key={a}>{a}</List.Item>)}</List>
            </Alert>
          )}
          {iniciar.isError && <Erro erro={iniciar.error} />}
          <Group justify="flex-end">
            <Button size="md" onClick={comecar} disabled={!podeIniciar} loading={iniciar.isPending}
              leftSection={<i className="bi bi-play-fill" />}>
              Começar lote com {unicos.length} endereço(s)
            </Button>
          </Group>
        </Stack>
      </Paper>

      <Modal opened={confirmandoExtracao} onClose={() => setConfirmandoExtracao(false)}
        title="Autorizar extração de TSSR?" centered>
        <Stack>
          <Text size="sm">
            Com a extração, a Ação 5.2B pode processar o TSSR pendente de cada endereço:
          </Text>
          <List size="sm">
            <List.Item>lê arquivos da pasta de Input;</List.Item>
            <List.Item>carrega as tabelas de TSSR no BigQuery;</List.Item>
            <List.Item>move o arquivo para Processados ou Error.</List.Item>
          </List>
          <Text size="sm">O lote roda um endereço por vez.</Text>
          <Group justify="flex-end">
            <Button variant="default" onClick={() => setConfirmandoExtracao(false)}>Cancelar</Button>
            <Button color="orange" onClick={() => {
              setPermitirExtracao(true);
              setConfirmandoExtracao(false);
            }}>
              Autorizar
            </Button>
          </Group>
        </Stack>
      </Modal>
    </Stack>
  );
}