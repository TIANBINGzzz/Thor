CREATE TABLE `files` (
	`id` text PRIMARY KEY NOT NULL,
	`session_id` text NOT NULL,
	`owner_id` text NOT NULL,
	`name` text NOT NULL,
	`content_type` text NOT NULL,
	`size` integer NOT NULL,
	`storage_key` text NOT NULL,
	`created_at` integer NOT NULL,
	FOREIGN KEY (`session_id`) REFERENCES `sessions`(`id`) ON UPDATE no action ON DELETE cascade
);
--> statement-breakpoint
CREATE UNIQUE INDEX `files_storage_key_unique` ON `files` (`storage_key`);--> statement-breakpoint
CREATE INDEX `idx_files_session_created` ON `files` (`session_id`,`created_at`);--> statement-breakpoint
CREATE TABLE `messages` (
	`id` text PRIMARY KEY NOT NULL,
	`session_id` text NOT NULL,
	`owner_id` text NOT NULL,
	`role` text NOT NULL,
	`content` text NOT NULL,
	`token_count` integer,
	`cost` real,
	`created_at` integer NOT NULL,
	FOREIGN KEY (`session_id`) REFERENCES `sessions`(`id`) ON UPDATE no action ON DELETE cascade
);
--> statement-breakpoint
CREATE INDEX `idx_messages_session_created` ON `messages` (`session_id`,`created_at`);--> statement-breakpoint
CREATE TABLE `sessions` (
	`id` text PRIMARY KEY NOT NULL,
	`owner_id` text NOT NULL,
	`title` text DEFAULT 'New chat' NOT NULL,
	`model_id` text DEFAULT 'qwen-plus' NOT NULL,
	`created_at` integer NOT NULL,
	`updated_at` integer NOT NULL
);
--> statement-breakpoint
CREATE INDEX `idx_sessions_owner_updated` ON `sessions` (`owner_id`,`updated_at`);
