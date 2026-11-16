/** As respostas reais da API, gravadas pelo teste do servidor
 * (bpr-agent/tests/test_servidor.py, test_exemplos_de_resposta_para_o_frontend).
 *
 * Cada uma é conferida contra o tipo de api/tipos.ts. O JSON importado
 * chega com os tipos "largos" (string em vez de "concluido"), então a
 * conferência usa Largo<T>: a mesma forma, com literais alargados. Campo
 * que sumiu ou mudou de nome na API quebra o tsc aqui. */

import acoes from "../../../tests/dourados/api/acoes.json";
import ambiente from "../../../tests/dourados/api/ambiente.json";
import conversa from "../../../tests/dourados/api/conversa.json";
import endereco from "../../../tests/dourados/api/endereco.json";
import escopo from "../../../tests/dourados/api/escopo.json";
import lote from "../../../tests/dourados/api/lote.json";
import lotes from "../../../tests/dourados/api/lotes.json";
import resultados from "../../../tests/dourados/api/resultados.json";
import saude from "../../../tests/dourados/api/saude.json";
import type {
  Acao,
  Ambiente,
  Conversa,
  DetalheEndereco,
  Escopo,
  LinhaResultado,
  Lote,
  LoteNaLista,
  Saude,
} from "../api/tipos";

type Largo<T> = T extends string
  ? string
  : T extends number
    ? number
    : T extends boolean
      ? boolean
      : T extends null | undefined
        ? T
        : T extends readonly [unknown, ...unknown[]]
          ? Largo<T[number]>[]
          : T extends readonly (infer E)[]
            ? Largo<E>[]
            : T extends object
              ? { [K in keyof T]: Largo<T[K]> }
              : T;

export const exemplos = {
  saude: saude satisfies Largo<Saude>,
  acoes: acoes.acoes satisfies Largo<Acao[]>,
  escopo: escopo satisfies Largo<Escopo>,
  ambiente: ambiente satisfies Largo<Ambiente>,
  lotes: lotes.lotes satisfies Largo<LoteNaLista[]>,
  lote: lote satisfies Largo<Lote>,
  endereco: endereco satisfies Largo<DetalheEndereco>,
  resultados: resultados.linhas satisfies Largo<LinhaResultado[]>,
  conversa: conversa satisfies Largo<Conversa>,
};

/** O exemplo com o tipo estreito, para passar a componentes. A forma já
 * foi conferida acima; os valores literais, os testes conferem rodando. */
export function como<T>(valor: unknown): T {
  return structuredClone(valor) as T;
}
