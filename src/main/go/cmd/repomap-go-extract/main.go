package main

import (
	"bufio"
	"errors"
	"fmt"
	"io"
	"os"
	"path/filepath"

	"github.com/lair001/repo-map-go-helper/internal/extraction"
	"github.com/lair001/repo-map-go-helper/internal/pathscope"
	"github.com/lair001/repo-map-go-helper/internal/protocol"
)

const (
	maxFileBytes    = 32 << 20
	maxObservations = 250_000
)

func main() {
	os.Exit(run(os.Args[1:], os.Stdin, os.Stdout, os.Stderr))
}

func run(args []string, stdin io.Reader, stdout io.Writer, stderr io.Writer) int {
	if len(args) == 1 && args[0] == "--protocol-version" {
		if _, err := fmt.Fprintln(stdout, protocol.ProtocolVersion); err != nil {
			return processError(stderr, "failed to write protocol version")
		}
		return 0
	}
	if len(args) != 2 || args[0] != "--root" || args[1] == "" {
		return processError(stderr, "invalid helper arguments")
	}
	root, err := filepath.EvalSymlinks(args[1])
	if err != nil {
		return processError(stderr, "invalid repository root")
	}

	scanner := bufio.NewScanner(stdin)
	scanner.Buffer(make([]byte, 64*1024), protocol.MaxProtocolLineBytes)
	expectedSequence := 0
	for scanner.Scan() {
		request, err := protocol.DecodeRequest(scanner.Bytes())
		if err != nil || request.Sequence != expectedSequence {
			return processError(stderr, "invalid protocol request")
		}
		if !processFile(root, request, stdout, stderr) {
			return 1
		}
		expectedSequence++
	}
	if err := scanner.Err(); err != nil {
		return processError(stderr, "protocol input exceeded its bound")
	}
	return 0
}

func processFile(
	root string,
	request protocol.Request,
	stdout io.Writer,
	stderr io.Writer,
) bool {
	path, err := pathscope.Resolve(root, request.Path, maxFileBytes)
	if errors.Is(err, pathscope.ErrFileTooLarge) {
		if !writeDiagnostic(stdout, request, "go-file-limit", 0, "Go file exceeds the configured size limit") {
			processError(stderr, "failed to write protocol response")
			return false
		}
		return writeFileEnd(stdout, request, 0, 1, true, stderr)
	}
	if err != nil {
		processError(stderr, "invalid repository-relative Go file path")
		return false
	}

	result := extraction.ParseFile(path, request.Path)
	observations := result.Observations
	truncated := result.Truncated
	if len(observations) > maxObservations {
		observations = observations[:maxObservations]
		truncated = true
	}
	for index := range observations {
		observation := observations[index]
		if err := protocol.WriteResponse(stdout, protocol.Response{
			ProtocolVersion: protocol.ProtocolVersion,
			Type:            "observation",
			Sequence:        request.Sequence,
			Path:            request.Path,
			Observation:     &observation,
		}); err != nil {
			processError(stderr, "failed to write protocol response")
			return false
		}
	}
	for _, diagnostic := range result.Diagnostics {
		if !writeDiagnostic(
			stdout,
			request,
			diagnostic.Code,
			diagnostic.Line,
			diagnostic.Message,
		) {
			processError(stderr, "failed to write protocol response")
			return false
		}
	}
	return writeFileEnd(
		stdout,
		request,
		len(observations),
		len(result.Diagnostics),
		truncated,
		stderr,
	)
}

func writeDiagnostic(
	stdout io.Writer,
	request protocol.Request,
	code string,
	line int,
	message string,
) bool {
	return protocol.WriteResponse(stdout, protocol.Response{
		ProtocolVersion: protocol.ProtocolVersion,
		Type:            "diagnostic",
		Sequence:        request.Sequence,
		Path:            request.Path,
		Severity:        "warning",
		Code:            code,
		Line:            line,
		Message:         message,
	}) == nil
}

func writeFileEnd(
	stdout io.Writer,
	request protocol.Request,
	observationCount int,
	diagnosticCount int,
	truncated bool,
	stderr io.Writer,
) bool {
	if err := protocol.WriteResponse(stdout, protocol.Response{
		ProtocolVersion:  protocol.ProtocolVersion,
		Type:             "file_end",
		Sequence:         request.Sequence,
		Path:             request.Path,
		ObservationCount: observationCount,
		DiagnosticCount:  diagnosticCount,
		Truncated:        truncated,
	}); err != nil {
		processError(stderr, "failed to write protocol response")
		return false
	}
	return true
}

func processError(stderr io.Writer, message string) int {
	_, _ = fmt.Fprintln(stderr, message)
	return 1
}
