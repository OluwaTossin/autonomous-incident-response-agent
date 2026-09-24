"""Injected boto3 SQS adapter; queue creation remains infrastructure work."""

from __future__ import annotations

from typing import Any

from botocore.config import Config

from app.jobs.contracts import QueueMessage


def create_sqs_client(
    *,
    region: str,
    endpoint_url: str | None = None,
    connect_timeout_seconds: float = 3.0,
    read_timeout_seconds: float = 25.0,
    max_attempts: int = 3,
):
    import boto3

    return boto3.client(
        "sqs",
        region_name=region,
        endpoint_url=endpoint_url,
        config=Config(
            connect_timeout=connect_timeout_seconds,
            read_timeout=read_timeout_seconds,
            retries={"max_attempts": max_attempts, "mode": "standard"},
        ),
    )


class Boto3SqsQueue:
    def __init__(self, client: Any, queue_url: str) -> None:
        if not queue_url.strip():
            raise ValueError("SQS queue URL is required")
        self._client = client
        self._queue_url = queue_url

    def send(self, message: str) -> str | None:
        response = self._client.send_message(
            QueueUrl=self._queue_url,
            MessageBody=message,
        )
        return response.get("MessageId")

    def send_batch(self, messages: tuple[str, ...]) -> tuple[str | None, ...]:
        if not messages:
            return ()
        if len(messages) > 10:
            raise ValueError("SQS send batches cannot exceed 10 messages")
        response = self._client.send_message_batch(
            QueueUrl=self._queue_url,
            Entries=[{"Id": str(index), "MessageBody": body} for index, body in enumerate(messages)],
        )
        failed = {entry["Id"] for entry in response.get("Failed", ())}
        successful = {
            entry["Id"]: entry.get("MessageId")
            for entry in response.get("Successful", ())
        }
        if failed:
            raise RuntimeError("SQS batch publish failed")
        return tuple(successful.get(str(index)) for index in range(len(messages)))

    def receive(
        self,
        *,
        max_messages: int,
        wait_time_seconds: int,
        visibility_timeout: int,
    ) -> tuple[QueueMessage, ...]:
        if not 1 <= max_messages <= 10:
            raise ValueError("SQS receive batch size must be between 1 and 10")
        response = self._client.receive_message(
            QueueUrl=self._queue_url,
            MaxNumberOfMessages=max_messages,
            WaitTimeSeconds=wait_time_seconds,
            VisibilityTimeout=visibility_timeout,
            AttributeNames=["ApproximateReceiveCount"],
        )
        return tuple(self._message(item) for item in response.get("Messages", ()))

    def delete(self, message: QueueMessage) -> None:
        self._client.delete_message(
            QueueUrl=self._queue_url,
            ReceiptHandle=message.receipt_handle,
        )

    def change_visibility(self, message: QueueMessage, timeout_seconds: int) -> None:
        self._client.change_message_visibility(
            QueueUrl=self._queue_url,
            ReceiptHandle=message.receipt_handle,
            VisibilityTimeout=timeout_seconds,
        )

    @staticmethod
    def _message(value: dict[str, Any]) -> QueueMessage:
        attributes = value.get("Attributes") or {}
        receive_count = attributes.get("ApproximateReceiveCount")
        return QueueMessage(
            body=value["Body"],
            receipt_handle=value["ReceiptHandle"],
            message_id=value.get("MessageId"),
            receive_count=int(receive_count) if receive_count is not None else None,
        )
