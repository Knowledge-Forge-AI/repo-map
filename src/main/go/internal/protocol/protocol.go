// Package protocol defines RepoMap's versioned Go helper JSONL contract.
package protocol

import (
	"bytes"
	"encoding/json"
	"errors"
	"fmt"
	"io"
)

const (
	ProtocolVersion      = 1
	MaxProtocolLineBytes = 1 << 20
)

var ErrInvalidMessage = errors.New("invalid protocol message")

type Request struct {
	ProtocolVersion int    `json:"protocol_version"`
	Type            string `json:"type"`
	Sequence        int    `json:"sequence"`
	Path            string `json:"path"`
}

type Observation struct {
	SchemaVersion    int            `json:"schema_version"`
	Kind             string         `json:"kind"`
	SourceID         string         `json:"source_id"`
	Path             string         `json:"path"`
	Confidence       string         `json:"confidence"`
	Extractor        string         `json:"extractor"`
	ExtractorVersion string         `json:"extractor_version"`
	StartLine        int            `json:"start_line,omitempty"`
	EndLine          int            `json:"end_line,omitempty"`
	Name             string         `json:"name,omitempty"`
	Target           string         `json:"target,omitempty"`
	Metadata         map[string]any `json:"metadata"`
}

type Response struct {
	ProtocolVersion  int
	Type             string
	Sequence         int
	Path             string
	Observation      *Observation
	Severity         string
	Code             string
	Line             int
	Message          string
	ObservationCount int
	DiagnosticCount  int
	Truncated        bool
}

func DecodeRequest(line []byte) (Request, error) {
	if len(line) == 0 || len(line) > MaxProtocolLineBytes {
		return Request{}, ErrInvalidMessage
	}
	decoder := json.NewDecoder(bytes.NewReader(line))
	decoder.DisallowUnknownFields()
	var request Request
	if err := decoder.Decode(&request); err != nil {
		return Request{}, ErrInvalidMessage
	}
	if err := requireJSONEOF(decoder); err != nil {
		return Request{}, ErrInvalidMessage
	}
	if request.ProtocolVersion != ProtocolVersion || request.Type != "file" {
		return Request{}, ErrInvalidMessage
	}
	if request.Sequence < 0 || request.Path == "" {
		return Request{}, ErrInvalidMessage
	}
	return request, nil
}

func WriteResponse(writer io.Writer, response Response) error {
	payload, err := responsePayload(response)
	if err != nil {
		return err
	}
	encoded, err := json.Marshal(payload)
	if err != nil {
		return fmt.Errorf("encode protocol response: %w", err)
	}
	if len(encoded)+1 > MaxProtocolLineBytes {
		return ErrInvalidMessage
	}
	encoded = append(encoded, '\n')
	if _, err := writer.Write(encoded); err != nil {
		return fmt.Errorf("write protocol response: %w", err)
	}
	return nil
}

func responsePayload(response Response) (map[string]any, error) {
	if response.ProtocolVersion != ProtocolVersion || response.Sequence < 0 || response.Path == "" {
		return nil, ErrInvalidMessage
	}
	payload := map[string]any{
		"protocol_version": response.ProtocolVersion,
		"type":             response.Type,
		"sequence":         response.Sequence,
		"path":             response.Path,
	}
	switch response.Type {
	case "observation":
		if response.Observation == nil {
			return nil, ErrInvalidMessage
		}
		payload["observation"] = response.Observation
	case "diagnostic":
		if response.Severity == "" || response.Code == "" || response.Message == "" {
			return nil, ErrInvalidMessage
		}
		payload["severity"] = response.Severity
		payload["code"] = response.Code
		payload["message"] = response.Message
		if response.Line > 0 {
			payload["line"] = response.Line
		}
	case "file_end":
		if response.ObservationCount < 0 || response.DiagnosticCount < 0 {
			return nil, ErrInvalidMessage
		}
		payload["observation_count"] = response.ObservationCount
		payload["diagnostic_count"] = response.DiagnosticCount
		payload["truncated"] = response.Truncated
	default:
		return nil, ErrInvalidMessage
	}
	return payload, nil
}

func requireJSONEOF(decoder *json.Decoder) error {
	var extra any
	if err := decoder.Decode(&extra); !errors.Is(err, io.EOF) {
		return ErrInvalidMessage
	}
	return nil
}
