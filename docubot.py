"""
Core DocuBot class responsible for:
- Loading documents from the docs/ folder
- Building a simple retrieval index (Phase 1)
- Retrieving relevant snippets (Phase 1)
- Supporting retrieval only answers
- Supporting RAG answers when paired with Gemini (Phase 2)
"""

import os
import glob
import re


STOPWORDS = {
    "a", "about", "all", "an", "and", "any", "are", "as", "at",
    "based", "be", "by", "can", "doc", "docs", "documentation",
    "do", "does", "for", "from", "how", "i", "in", "is", "it",
    "mention", "mentions", "of", "on", "or", "should", "the", "these",
    "this", "to", "what", "when", "where", "which", "who", "why", "with"
}


class DocuBot:
    def __init__(self, docs_folder="docs", llm_client=None):
        """
        docs_folder: directory containing project documentation files
        llm_client: optional Gemini client for LLM based answers
        """
        self.docs_folder = docs_folder
        self.llm_client = llm_client

        # Load documents into memory
        self.documents = self.load_documents()  # List of (filename, text)

        # Break documents into smaller retrieval units.
        self.sections = self.build_sections(self.documents)

        # Build a retrieval index (implemented in Phase 1)
        self.index = self.build_index(self.sections)

    def _tokenize(self, text):
        """
        Lowercase text and split into simple word tokens.
        """
        return re.findall(r"\b\w+\b", text.lower())

    def _content_tokens(self, text):
        """
        Filter text down to the tokens that carry retrieval meaning.
        """
        return [
            token for token in self._tokenize(text)
            if token not in STOPWORDS and len(token) > 2
        ]

    # -----------------------------------------------------------
    # Document Loading
    # -----------------------------------------------------------

    def load_documents(self):
        """
        Loads all .md and .txt files inside docs_folder.
        Returns a list of tuples: (filename, text)
        """
        docs = []
        pattern = os.path.join(self.docs_folder, "*.*")
        for path in glob.glob(pattern):
            if path.endswith(".md") or path.endswith(".txt"):
                with open(path, "r", encoding="utf8") as f:
                    text = f.read()
                filename = os.path.basename(path)
                docs.append((filename, text))
        return docs

    # -----------------------------------------------------------
    # Index Construction (Phase 1)
    # -----------------------------------------------------------

    def build_sections(self, documents):
        """
        Split each document into smaller sections so retrieval can return
        focused snippets instead of entire files.

        Sections are based on blank-line separated blocks, with markdown
        headings attached to the block that follows them for context.
        """
        sections = []

        for filename, text in documents:
            blocks = [block.strip()
                      for block in re.split(r"\n\s*\n", text) if block.strip()]
            current_heading = ""

            for block in blocks:
                if block.startswith("#"):
                    current_heading = block
                    continue

                if current_heading:
                    section_text = f"{current_heading}\n\n{block}"
                else:
                    section_text = block

                sections.append((filename, section_text))

        return sections

    def build_index(self, sections):
        """
        Build a tiny inverted index mapping lowercase words to the section
        numbers where they appear.

        Example structure:
        {
            "token": [0, 4],
            "database": [7]
        }

        Keep this simple: split on whitespace, lowercase tokens,
        ignore punctuation if needed.
        """
        index = {}
        for section_id, (_, text) in enumerate(sections):
            seen_tokens = set(self._content_tokens(text))
            for token in seen_tokens:
                index.setdefault(token, []).append(section_id)
        return index

    # -----------------------------------------------------------
    # Scoring and Retrieval (Phase 1)
    # -----------------------------------------------------------

    def score_document(self, query, text):
        """
        TODO (Phase 1):
        Return a simple relevance score for how well the text matches the query.

        Suggested baseline:
        - Convert query into lowercase words
        - Count how many appear in the text
        - Return the count as the score
        """
        query_tokens = self._content_tokens(query)
        if not query_tokens:
            return 0

        text_tokens = self._content_tokens(text)
        unique_tokens = set(text_tokens)
        score = 0
        for token in query_tokens:
            if token in unique_tokens:
                score += text_tokens.count(token)
        return score

    def _match_details(self, query, text):
        """
        Return the numeric score and the matched content tokens for a section.
        """
        query_tokens = self._content_tokens(query)
        if not query_tokens:
            return 0, []

        text_tokens = self._content_tokens(text)
        unique_tokens = set(text_tokens)
        matched_tokens = [
            token for token in query_tokens if token in unique_tokens]
        score = sum(text_tokens.count(token) for token in matched_tokens)
        return score, matched_tokens

    def _has_useful_context(self, query, scored_results):
        """
        Decide whether retrieval found enough evidence to support an answer.

        In this system, "useful context" means:
        - the query contains at least one content-bearing token, and
        - at least one retrieved section matches one of those content tokens.
        """
        query_tokens = self._content_tokens(query)
        if not query_tokens:
            return False

        if not scored_results:
            return False

        best_score, _, _, matched_tokens = scored_results[0]
        return best_score > 0 and bool(matched_tokens)

    def _retrieve_scored(self, query, top_k=3):
        """
        Internal retrieval helper that keeps scores and matched tokens so the
        answering layer can decide whether the evidence is strong enough.
        """
        query_tokens = self._content_tokens(query)
        if not query_tokens:
            return []

        candidate_section_ids = set()

        for token in query_tokens:
            candidate_section_ids.update(self.index.get(token, []))

        if not candidate_section_ids:
            return []

        results = []
        for section_id in candidate_section_ids:
            filename, text = self.sections[section_id]
            score, matched_tokens = self._match_details(query, text)
            if score > 0:
                results.append((score, filename, text, matched_tokens))

        results.sort(key=lambda item: (-item[0], item[1]))
        return results[:top_k]

    def retrieve(self, query, top_k=3):
        """
        TODO (Phase 1):
        Use the index and scoring function to select top_k relevant document snippets.

        Return a list of (filename, text) sorted by score descending.
        """
        scored_results = self._retrieve_scored(query, top_k=top_k)
        return [(filename, text) for _, filename, text, _ in scored_results]

    # -----------------------------------------------------------
    # Answering Modes
    # -----------------------------------------------------------

    def answer_retrieval_only(self, query, top_k=3):
        """
        Phase 1 retrieval only mode.
        Returns raw snippets and filenames with no LLM involved.
        """
        scored_results = self._retrieve_scored(query, top_k=top_k)

        if not self._has_useful_context(query, scored_results):
            return "I do not know based on these docs."

        formatted = []
        for _, filename, text, _ in scored_results:
            formatted.append(f"[{filename}]\n{text}\n")

        return "\n---\n".join(formatted)

    def answer_rag(self, query, top_k=3):
        """
        Phase 2 RAG mode.
        Uses student retrieval to select snippets, then asks Gemini
        to generate an answer using only those snippets.
        """
        if self.llm_client is None:
            raise RuntimeError(
                "RAG mode requires an LLM client. Provide a GeminiClient instance."
            )

        scored_results = self._retrieve_scored(query, top_k=top_k)
        snippets = [(filename, text)
                    for _, filename, text, _ in scored_results]

        if not self._has_useful_context(query, scored_results):
            return "I do not know based on these docs."

        return self.llm_client.answer_from_snippets(query, snippets)

    # -----------------------------------------------------------
    # Bonus Helper: concatenated docs for naive generation mode
    # -----------------------------------------------------------

    def full_corpus_text(self):
        """
        Returns all documents concatenated into a single string.
        This is used in Phase 0 for naive 'generation only' baselines.
        """
        return "\n\n".join(text for _, text in self.documents)
