package main

import (
	"bufio"
	"bytes"
	"encoding/json"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"github.com/lair001/repo-map-go-helper/internal/protocol"
)

func TestRunProcessesFilesSequentiallyAndReportsCounts(t *testing.T) {
	root := t.TempDir()
	writeGoFile(t, root, "a.go", "package sample\nconst A = 1\n")
	writeGoFile(t, root, "b.go", "package sample\nvar B = 2\n")
	input := strings.Join([]string{
		`{"protocol_version":1,"type":"file","sequence":0,"path":"a.go"}`,
		`{"protocol_version":1,"type":"file","sequence":1,"path":"b.go"}`,
		"",
	}, "\n")
	var stdout bytes.Buffer
	var stderr bytes.Buffer

	exitCode := run([]string{"--root", root}, strings.NewReader(input), &stdout, &stderr)

	if exitCode != 0 {
		t.Fatalf("run() = %d, stderr = %q", exitCode, stderr.String())
	}
	if stderr.Len() != 0 {
		t.Fatalf("stderr = %q", stderr.String())
	}
	messages := decodeLines(t, stdout.Bytes())
	fileEnds := messagesByType(messages, "file_end")
	if len(fileEnds) != 2 {
		t.Fatalf("file_end messages = %d", len(fileEnds))
	}
	if fileEnds[0]["sequence"] != float64(0) || fileEnds[1]["sequence"] != float64(1) {
		t.Fatalf("file_end order = %#v", fileEnds)
	}
	if fileEnds[0]["observation_count"] != float64(2) || fileEnds[1]["observation_count"] != float64(2) {
		t.Fatalf("observation counts = %#v", fileEnds)
	}
}

func TestRunEmitsBoundedDiagnosticsAndContinuesAfterMalformedFile(t *testing.T) {
	root := t.TempDir()
	writeGoFile(t, root, "partial.go", "package partial\nconst Before = 1\ntype Broken struct {\n")
	writeGoFile(t, root, "good.go", "package good\ntype Ready string\n")
	input := strings.Join([]string{
		`{"protocol_version":1,"type":"file","sequence":0,"path":"partial.go"}`,
		`{"protocol_version":1,"type":"file","sequence":1,"path":"good.go"}`,
		"",
	}, "\n")
	var stdout bytes.Buffer
	var stderr bytes.Buffer

	exitCode := run([]string{"--root", root}, strings.NewReader(input), &stdout, &stderr)

	if exitCode != 0 {
		t.Fatalf("run() = %d, stderr = %q", exitCode, stderr.String())
	}
	messages := decodeLines(t, stdout.Bytes())
	diagnostics := messagesByType(messages, "diagnostic")
	if len(diagnostics) == 0 {
		t.Fatal("no diagnostic messages")
	}
	for _, diagnostic := range diagnostics {
		message, _ := diagnostic["message"].(string)
		if strings.Contains(message, root) || strings.Contains(message, "Broken") {
			t.Fatalf("diagnostic leaked source detail: %#v", diagnostic)
		}
	}
	fileEnds := messagesByType(messages, "file_end")
	if len(fileEnds) != 2 || fileEnds[1]["diagnostic_count"] != float64(0) {
		t.Fatalf("file_end messages = %#v", fileEnds)
	}
}

func TestRunReportsOversizedFileWithoutTerminatingSession(t *testing.T) {
	root := t.TempDir()
	writeGoFile(t, root, "large.go", strings.Repeat("x", maxFileBytes+1))
	writeGoFile(t, root, "good.go", "package good\n")
	input := strings.Join([]string{
		`{"protocol_version":1,"type":"file","sequence":0,"path":"large.go"}`,
		`{"protocol_version":1,"type":"file","sequence":1,"path":"good.go"}`,
		"",
	}, "\n")
	var stdout bytes.Buffer
	var stderr bytes.Buffer

	exitCode := run([]string{"--root", root}, strings.NewReader(input), &stdout, &stderr)

	if exitCode != 0 {
		t.Fatalf("run() = %d, stderr = %q", exitCode, stderr.String())
	}
	messages := decodeLines(t, stdout.Bytes())
	diagnostics := messagesByType(messages, "diagnostic")
	if len(diagnostics) != 1 || diagnostics[0]["code"] != "go-file-limit" {
		t.Fatalf("diagnostics = %#v", diagnostics)
	}
	fileEnds := messagesByType(messages, "file_end")
	if fileEnds[0]["truncated"] != true || fileEnds[1]["observation_count"] != float64(1) {
		t.Fatalf("file_end messages = %#v", fileEnds)
	}
}

func TestRunRejectsInvalidProtocolWithoutLeakingArguments(t *testing.T) {
	root := t.TempDir()
	input := `{"protocol_version":2,"type":"file","sequence":0,"path":"/private/source.go"}` + "\n"
	var stdout bytes.Buffer
	var stderr bytes.Buffer

	exitCode := run([]string{"--root", root}, strings.NewReader(input), &stdout, &stderr)

	if exitCode == 0 {
		t.Fatal("run() succeeded")
	}
	if stdout.Len() != 0 {
		t.Fatalf("stdout = %q", stdout.String())
	}
	if strings.Contains(stderr.String(), root) || strings.Contains(stderr.String(), "/private/source.go") {
		t.Fatalf("stderr leaked path: %q", stderr.String())
	}
}

func TestRunPrintsProtocolVersion(t *testing.T) {
	var stdout bytes.Buffer
	var stderr bytes.Buffer

	exitCode := run([]string{"--protocol-version"}, strings.NewReader(""), &stdout, &stderr)

	if exitCode != 0 || stdout.String() != "1\n" || stderr.Len() != 0 {
		t.Fatalf("run() = %d, stdout = %q, stderr = %q", exitCode, stdout.String(), stderr.String())
	}
}

func TestRunReportsProtocolVersionWriteFailure(t *testing.T) {
	var stderr bytes.Buffer

	exitCode := run(
		[]string{"--protocol-version"},
		strings.NewReader(""),
		failingOutput{},
		&stderr,
	)

	if exitCode == 0 || stderr.String() != "failed to write protocol version\n" {
		t.Fatalf("run() = %d, stderr = %q", exitCode, stderr.String())
	}
}

func TestRunRejectsInvalidArgumentsRootPathAndSequence(t *testing.T) {
	root := t.TempDir()
	tests := []struct {
		args  []string
		input string
	}{
		{args: nil},
		{args: []string{"--root", filepath.Join(root, "missing")}},
		{
			args:  []string{"--root", root},
			input: `{"protocol_version":1,"type":"file","sequence":1,"path":"file.go"}` + "\n",
		},
		{
			args:  []string{"--root", root},
			input: `{"protocol_version":1,"type":"file","sequence":0,"path":"missing.go"}` + "\n",
		},
		{
			args:  []string{"--root", root},
			input: strings.Repeat("x", 1<<20+1),
		},
	}
	for _, test := range tests {
		var stdout bytes.Buffer
		var stderr bytes.Buffer
		if exitCode := run(test.args, strings.NewReader(test.input), &stdout, &stderr); exitCode == 0 {
			t.Fatalf("run(%#v) succeeded", test.args)
		}
		if stderr.Len() == 0 || stderr.Len() > 1024 {
			t.Fatalf("stderr length = %d", stderr.Len())
		}
	}
}

func TestRunFailsSafelyWhenProtocolOutputCannotBeWritten(t *testing.T) {
	root := t.TempDir()
	writeGoFile(t, root, "file.go", "package sample\n")
	input := `{"protocol_version":1,"type":"file","sequence":0,"path":"file.go"}` + "\n"
	var stderr bytes.Buffer

	exitCode := run([]string{"--root", root}, strings.NewReader(input), failingOutput{}, &stderr)

	if exitCode == 0 || stderr.Len() == 0 {
		t.Fatalf("run() = %d, stderr = %q", exitCode, stderr.String())
	}
}

func TestResponseHelpersPropagateWriterFailures(t *testing.T) {
	request := protocol.Request{
		ProtocolVersion: protocol.ProtocolVersion,
		Type:            "file",
		Sequence:        0,
		Path:            "file.go",
	}
	if writeDiagnostic(failingOutput{}, request, "go-parse-error", 1, "syntax error") {
		t.Fatal("writeDiagnostic() succeeded")
	}
	var stderr bytes.Buffer
	if writeFileEnd(failingOutput{}, request, 0, 0, false, &stderr) {
		t.Fatal("writeFileEnd() succeeded")
	}
	if stderr.String() != "failed to write protocol response\n" {
		t.Fatalf("stderr = %q", stderr.String())
	}
}

type failingOutput struct{}

func (failingOutput) Write([]byte) (int, error) {
	return 0, os.ErrClosed
}

func writeGoFile(t *testing.T, root string, relative string, content string) {
	t.Helper()
	path := filepath.Join(root, filepath.FromSlash(relative))
	if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(path, []byte(content), 0o644); err != nil {
		t.Fatal(err)
	}
}

func decodeLines(t *testing.T, payload []byte) []map[string]any {
	t.Helper()
	var messages []map[string]any
	scanner := bufio.NewScanner(bytes.NewReader(payload))
	for scanner.Scan() {
		var message map[string]any
		if err := json.Unmarshal(scanner.Bytes(), &message); err != nil {
			t.Fatal(err)
		}
		messages = append(messages, message)
	}
	if err := scanner.Err(); err != nil {
		t.Fatal(err)
	}
	return messages
}

func messagesByType(messages []map[string]any, messageType string) []map[string]any {
	var selected []map[string]any
	for _, message := range messages {
		if message["type"] == messageType {
			selected = append(selected, message)
		}
	}
	return selected
}
