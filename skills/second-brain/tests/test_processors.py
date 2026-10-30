"""Funções puras dos processadores: detecção do tipo, montagem dos argumentos e legendas para texto
(SPEC-0022: UT-01 a UT-03).

Contrato esperado das funções de scripts/brain.py (o Implementer segue estes testes; seções 4 e 6 da spec).
Nenhuma delas faz I/O nem roda processo.

    detect_kind(source: str) -> str | None
        "youtube": URL http(s) cujo host é exatamente youtube.com, www.youtube.com, m.youtube.com ou youtu.be
                   (sem diferença de maiúsculas no host); outro esquema (ftp://...) ou outro host -> None.
        "video"  : extensão .mp4 .mov .mkv .webm .avi;  "audio": .mp3 .m4a .wav .ogg .opus;  "pdf": .pdf
                   (extensão sem diferença de maiúsculas: "aula.MP4" -> "video"). Qualquer outra coisa -> None.

    build_args(command: str, input: str, output: str, output_dir: str) -> list[str]
        shlex.split(command) e, em cada argumento, {input}, {output} e {output_dir} trocados pelos valores
        (uma única passada: um valor que contém "{output}" entra literal). O valor nunca é dividido nem
        interpretado: um nome com espaço, ";", "$()" e aspas vira um argumento só. Sem shell.

    subtitles_to_text(text: str, timestamps: bool = False, url: str | None = None) -> str
        Legenda .vtt ou .srt -> texto. Some: o cabeçalho WEBVTT e seus metadados (Kind:, Language:), os números
        das legendas .srt, as linhas de tempo ("-->"), as marcações (<c>, </c>, <i>, <b>, <00:00:01.500>) e as
        linhas vazias. Cada linha de texto entra uma vez só: uma linha que repete a de uma legenda anterior (as
        legendas automáticas do YouTube repetem a linha anterior) não é repetida.
        timestamps=False: só o texto, na ordem.
        timestamps=True : uma linha "[mm:ss] texto" por linha de texto, com o início (segundos inteiros, para
                          baixo) da primeira legenda em que ela aparece.
        timestamps=True e url de YouTube: "[mm:ss](<url>?t=<segundos>s) texto", ou "&t=" quando a URL já tem
                          query (https://www.youtube.com/watch?v=abc -> https://www.youtube.com/watch?v=abc&t=65s).

    run_processor(kind: str, source: str, processors: dict, timestamps: bool = False) -> str
        (coberto pela CLI em test_processors_cli e pela regra de arquitetura em test_architecture/UT-04)
        O único ponto do brain.py que roda processo externo: build_args com o `command` de processors[kind],
        subprocess.run(args, timeout=int(timeout or 1800), capture_output=True) sem shell, num diretório
        temporário; texto de {output}, do maior arquivo com a extensão `output` em {output_dir} ou do stdout;
        .vtt/.srt passam por subtitles_to_text (com a URL quando kind é youtube). Executável ausente, exit != 0,
        timeout ou texto vazio -> BrainError(code 1) "processador <kind> falhou: <motivo>" com o stderr resumido
        (até 500 caracteres).
"""
import unittest

from brain_support import fn

VTT = """WEBVTT
Kind: captions
Language: pt

00:00:01.000 --> 00:00:04.000 align:start position:0%
Olá<00:00:01.500><c> turma</c>

00:00:04.000 --> 00:00:04.010 align:start position:0%
Olá turma
\x20

00:00:04.010 --> 00:00:08.000 align:start position:0%
Olá turma
hoje<00:00:05.000><c> limites</c>

00:01:05.000 --> 00:01:09.000
hoje limites
derivadas no fim
"""
VTT_LINES = (("00:01", 1, "Olá turma"), ("00:04", 4, "hoje limites"), ("01:05", 65, "derivadas no fim"))

SRT = """1
00:00:02,500 --> 00:00:05,000
<i>Bem-vindos</i> à aula

2
00:00:05,000 --> 00:00:07,000
Bem-vindos à aula

3
00:02:10,000 --> 00:02:12,000
Integral <b>definida</b>
"""
SRT_LINES = (("00:02", 2, "Bem-vindos à aula"), ("02:10", 130, "Integral definida"))


def lines(text):
    return [line.strip() for line in text.splitlines() if line.strip()]


class DetectKindTest(unittest.TestCase):
    def test_kinds_of_the_contract(self):
        """SPEC-0022:UT-01"""
        detect_kind = fn("detect_kind", "SPEC-0022")
        cases = {
            "https://www.youtube.com/watch?v=x": "youtube",
            "https://youtu.be/x": "youtube",
            "aula.MP4": "video",
            "nota.m4a": "audio",
            "slides.pdf": "pdf",
            "x.docx": None,
            "https://youtube.com/watch?v=x": "youtube",
            "https://m.youtube.com/watch?v=x": "youtube",
            "http://YouTu.be/x": "youtube",
            "/tmp/Aulas/aula 1.mov": "video",
            "a.mkv": "video", "a.webm": "video", "a.avi": "video",
            "a.mp3": "audio", "a.wav": "audio", "a.ogg": "audio", "a.opus": "audio",
            "https://youtube.com.evil.example/watch?v=x": None,
            "https://notyoutube.com/watch?v=x": None,
            "ftp://youtube.com/x": None,
            "https://example.com/x": None,
            "slides.pdf.txt": None,
        }
        for source, kind in cases.items():
            with self.subTest(source=source):
                self.assertEqual(detect_kind(source), kind)


class BuildArgsTest(unittest.TestCase):
    def test_each_marker_becomes_one_literal_argument_without_shell(self):
        """SPEC-0022:UT-02"""
        build_args = fn("build_args", "SPEC-0022")
        entrada = '/tmp/in/a b; $(rm -rf x) "c".pdf'
        out_dir = "/tmp/out dir"
        out_file = "/tmp/out dir/saida.txt"
        self.assertEqual(build_args("tool --in {input} -o {output_dir}/x", entrada, out_file, out_dir),
                         ["tool", "--in", entrada, "-o", "/tmp/out dir/x"])
        self.assertEqual(build_args("tool {input} {output}", entrada, out_file, out_dir),
                         ["tool", entrada, out_file])
        self.assertEqual(build_args("tool 'duas palavras' --file={input}", entrada, out_file, out_dir),
                         ["tool", "duas palavras", "--file=" + entrada])

    def test_a_value_with_a_marker_inside_is_kept_literally(self):
        """SPEC-0022:UT-02"""
        build_args = fn("build_args", "SPEC-0022")
        entrada = "/tmp/in/{output_dir} e {output}.pdf"
        self.assertEqual(build_args("tool {input} {output}", entrada, "/tmp/o/x.txt", "/tmp/o"),
                         ["tool", entrada, "/tmp/o/x.txt"])


class SubtitlesToTextTest(unittest.TestCase):
    def convert(self, *args, **kwargs):
        return fn("subtitles_to_text", "SPEC-0022")(*args, **kwargs)

    def assertClean(self, result):
        for junk in ("WEBVTT", "Kind:", "Language:", "-->", "<", ">", "align:"):
            self.assertNotIn(junk, result)

    def test_plain_text_without_header_markup_or_repeated_lines(self):
        """SPEC-0022:UT-03"""
        for name, subtitle, expected in (("vtt", VTT, VTT_LINES), ("srt", SRT, SRT_LINES)):
            with self.subTest(name):
                result = self.convert(subtitle)
                self.assertClean(result)
                self.assertEqual(" ".join(result.split()), " ".join(text for _, _, text in expected))
                self.assertFalse(any(line.isdigit() for line in lines(result)), result)

    def test_timestamps_become_mm_ss_lines(self):
        """SPEC-0022:UT-03"""
        for name, subtitle, expected in (("vtt", VTT, VTT_LINES), ("srt", SRT, SRT_LINES)):
            with self.subTest(name):
                result = self.convert(subtitle, timestamps=True)
                self.assertEqual(lines(result), [f"[{mmss}] {text}" for mmss, _, text in expected])

    def test_youtube_timestamps_link_to_the_moment(self):
        """SPEC-0022:UT-03"""
        for url, sep in (("https://youtu.be/abc", "?"), ("https://www.youtube.com/watch?v=abc", "&")):
            with self.subTest(url=url):
                result = self.convert(VTT, timestamps=True, url=url)
                self.assertEqual(lines(result),
                                 [f"[{mmss}]({url}{sep}t={secs}s) {text}" for mmss, secs, text in VTT_LINES])


if __name__ == "__main__":
    unittest.main()
